from decimal import Decimal

import pytest

from production_bot.live_adapter import LiveExecutionBlocked, LiveExecutionConfig, ProductionBinanceAdapter
from production_bot.reconciliation import reconcile_order


class FakeAdapter:
    def __init__(self, result):
        self.result = result

    def submit(self, order):
        return self.result


class FakeOrder:
    pass


def test_btcusdt_is_allowed_on_testnet():
    proposal = type("Proposal", (), {"symbol": "BTCUSDT"})()
    order = type("Authorized", (), {"proposal": proposal})()
    adapter = ProductionBinanceAdapter(
        FakeAdapter({"id": "1", "status": "closed", "trades": []}),
        LiveExecutionConfig(testnet=True, live_trading_enabled=False),
    )
    result, fills = adapter.submit(order)
    assert result["id"] == "1"
    assert fills == []


def test_live_execution_is_fail_closed_by_default():
    proposal = type("Proposal", (), {"symbol": "BTCUSDT"})()
    order = type("Authorized", (), {"proposal": proposal})()
    adapter = ProductionBinanceAdapter(
        FakeAdapter({"id": "1", "trades": []}),
        LiveExecutionConfig(testnet=False, live_trading_enabled=False),
    )
    with pytest.raises(LiveExecutionBlocked, match="LIVE_TRADING_DISABLED"):
        adapter.submit(order)


def test_symbol_allowlist_rejects_other_symbols():
    proposal = type("Proposal", (), {"symbol": "ETHUSDT"})()
    order = type("Authorized", (), {"proposal": proposal})()
    adapter = ProductionBinanceAdapter(
        FakeAdapter({"id": "1", "trades": []}),
        LiveExecutionConfig(testnet=True),
    )
    with pytest.raises(LiveExecutionBlocked, match="SYMBOL_NOT_ALLOWED"):
        adapter.submit(order)


def test_reconciliation_rejects_overfill():
    result = reconcile_order(
        "local-1",
        Decimal("0.001"),
        {"id": "exchange-1", "status": "closed", "filled": "0.002"},
    )
    assert not result.consistent
    assert result.reason == "INVALID_FILLED_QUANTITY"
