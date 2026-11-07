from decimal import Decimal
from fastapi.testclient import TestClient
from arbitrage.adapters.arbitrum import ArbitrumReadOnlyClient
from arbitrage.integrations.aave_v3 import AaveV3ReadOnlyClient
from arbitrage.scanner.engine import OpportunityScanner
from arbitrage.api.app import app

def test_scanner_returns_simulation_only_record():
    record = OpportunityScanner().scan_synthetic_fixture(Decimal("10000"))
    assert record["environment"] == "SIMULATION"
    assert record["quote_source"] == "SYNTHETIC_FIXTURE"
    assert record["market_data_verified"] is False
    assert record["executable"] is False
    assert record["transaction_submitted"] is False
    assert record["transaction_hash"] is None
    assert record["status"] == "SIMULATED"

def test_scanner_rejects_invalid_amount():
    import pytest
    with pytest.raises(ValueError):
        OpportunityScanner().scan_synthetic_fixture(Decimal("0"))

def test_aave_read_only_market_resolution():
    import json
    def transport(url, body, timeout):
        request = json.loads(body.decode())
        if request["method"] == "eth_chainId":
            result = "0xa4b1"
        elif request["method"] == "eth_call":
            result = "0x" + ("0" * 24) + "1111111111111111111111111111111111111111"
        elif request["method"] == "eth_getCode":
            result = "0x60016000"
        else:
            raise AssertionError("unexpected RPC method")
        return json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}).encode()
    rpc = ArbitrumReadOnlyClient("https://rpc.example.invalid", transport=transport)
    market = AaveV3ReadOnlyClient(
        rpc, "0x2222222222222222222222222222222222222222"
    ).inspect_market()
    assert market.chain_id == 42161
    assert market.pool == "0x1111111111111111111111111111111111111111"
    assert market.pool_has_code is True

def test_api_health_is_hard_locked():
    client = TestClient(app)
    data = client.get("/api/health").json()
    assert data["mode"] == "SIMULATION"
    assert data["signing_enabled"] is False
    assert data["transaction_submission_enabled"] is False
    assert data["deployment_enabled"] is False

def test_api_scan_and_dashboard():
    client = TestClient(app)
    assert client.get("/").status_code == 200
    response = client.post("/api/scan", json={"borrowed_amount":"5000"})
    assert response.status_code == 200
    assert response.json()["transaction_submitted"] is False
    assert response.json()["quote_source"] == "SYNTHETIC_FIXTURE"
