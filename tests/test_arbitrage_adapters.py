import json
from urllib.parse import parse_qs, urlparse

import pytest

from arbitrage.adapters.arbitrum import ArbitrumReadOnlyClient, RpcError
from arbitrage.adapters.binance_spot import (
    BinanceReadOnlyError,
    BinanceSpotReadOnlyClient,
)


def rpc_transport_for(result):
    def transport(url, body, timeout):
        request = json.loads(body.decode())
        assert request["jsonrpc"] == "2.0"
        return json.dumps({"jsonrpc": "2.0", "id": request["id"],
                           "result": result}).encode()
    return transport


def test_arbitrum_chain_identity_and_read_methods():
    client = ArbitrumReadOnlyClient(
        "https://arb.example.invalid/rpc",
        transport=rpc_transport_for("0xa4b1"),
    )
    assert client.require_arbitrum_one() == 42161


def test_arbitrum_rejects_non_https_endpoint():
    with pytest.raises(ValueError):
        ArbitrumReadOnlyClient("http://localhost:8545")


def test_arbitrum_rejects_transaction_submission_method():
    client = ArbitrumReadOnlyClient(
        "https://arb.example.invalid/rpc",
        transport=rpc_transport_for("0x1"),
    )
    with pytest.raises(ValueError, match="not allowed"):
        client.request("eth_sendRawTransaction", ["0xdeadbeef"])


def test_arbitrum_rejects_wrong_chain():
    client = ArbitrumReadOnlyClient(
        "https://arb.example.invalid/rpc",
        transport=rpc_transport_for("0x1"),
    )
    with pytest.raises(RpcError, match="Unexpected chain ID"):
        client.require_arbitrum_one()


def test_binance_market_data_uses_fixed_https_host():
    def transport(url, headers, timeout):
        assert url.startswith("https://api.binance.com/api/v3/ticker/price?")
        return b'{"symbol":"BTCUSDT","price":"65000.12"}'
    client = BinanceSpotReadOnlyClient(transport=transport)
    from decimal import Decimal
    assert client.ticker_price("BTCUSDT") == Decimal("65000.12")


def test_binance_signed_account_read_uses_signature_and_key_header():
    calls = []

    def transport(url, headers, timeout):
        calls.append((url, headers))
        if url.endswith("/api/v3/time"):
            return b'{"serverTime":1790000000000}'
        assert url.startswith("https://api.binance.com/api/v3/account?")
        assert headers["X-MBX-APIKEY"] == "test-read-only-key"
        query = parse_qs(urlparse(url).query)
        assert query["timestamp"] == ["1790000000000"]
        assert len(query["signature"][0]) == 64
        assert "test-read-only-secret" not in url
        return b'{"balances":[]}'
    client = BinanceSpotReadOnlyClient(
        api_key="test-read-only-key",
        api_secret="test-read-only-secret",
        transport=transport,
    )
    assert client.account_read_only() == {"balances": []}
    assert len(calls) == 2


def test_binance_account_read_fails_closed_without_credentials():
    client = BinanceSpotReadOnlyClient(transport=lambda *args: b'{}')
    with pytest.raises(BinanceReadOnlyError, match="local API credentials"):
        client.account_read_only()


def test_binance_symbol_validation_blocks_url_injection():
    client = BinanceSpotReadOnlyClient(transport=lambda *args: b'{}')
    with pytest.raises(ValueError):
        client.ticker_price("BTCUSDT&order=true")


def test_binance_endpoint_allowlist_rejects_mutation_route():
    client = BinanceSpotReadOnlyClient(transport=lambda *args: b'{}')
    with pytest.raises(ValueError, match="allowlisted"):
        client._get_json("/api/v3/order", {"symbol": "BTCUSDT"}, signed=True)
