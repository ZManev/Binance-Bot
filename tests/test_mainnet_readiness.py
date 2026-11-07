import json
from arbitrage.adapters.arbitrum import ArbitrumReadOnlyClient
from arbitrage.risk.mainnet_readiness import inspect_mainnet_readiness

def test_mainnet_readiness_is_always_locked(monkeypatch):
    monkeypatch.delenv("ARBITRUM_RPC_URL", raising=False)
    monkeypatch.delenv("AAVE_V3_ADDRESSES_PROVIDER", raising=False)
    report = inspect_mainnet_readiness()
    assert report.capital_cap_usdc == "50"
    assert report.execution_profile == "LIMITED_REQUESTED_BUT_NOT_IMPLEMENTED"
    assert report.execution_ready is False
    assert report.signing_enabled is False
    assert report.transaction_submission_enabled is False
    assert report.deployment_enabled is False

def test_readiness_checks_contract_code_without_writes(monkeypatch):
    monkeypatch.setenv("AAVE_V3_ADDRESSES_PROVIDER", "0x2222222222222222222222222222222222222222")
    methods = []
    def transport(url, body, timeout):
        req = json.loads(body.decode())
        methods.append(req["method"])
        if req["method"] == "eth_chainId":
            result = "0xa4b1"
        elif req["method"] == "eth_blockNumber":
            result = "0x1234"
        elif req["method"] == "eth_call":
            result = "0x" + ("0" * 24) + "1111111111111111111111111111111111111111"
        elif req["method"] == "eth_getCode":
            result = "0x60016000"
        else:
            raise AssertionError("unexpected RPC method: " + req["method"])
        return json.dumps({"jsonrpc":"2.0","id":1,"result":result}).encode()
    rpc = ArbitrumReadOnlyClient("https://rpc.example.invalid", transport=transport)
    report = inspect_mainnet_readiness(rpc)
    assert report.chain_id == 42161
    assert all(c.status == "PASS" for c in report.checks)
    assert set(methods) <= {"eth_chainId", "eth_blockNumber", "eth_call", "eth_getCode"}
    assert report.execution_ready is False
    assert report.transaction_submission_enabled is False
