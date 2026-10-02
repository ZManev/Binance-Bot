from decimal import Decimal

import pytest

from .fills import FillEvent
from .multi_exchange import CcxtExchangeAdapter, ExchangeCredentials
from .reconciliation import Reconciler


class StaticCredentials:
    def get(self, exchange_id):
        return ExchangeCredentials("key", "secret")


def test_supported_exchanges_are_explicit():
    assert {"binance", "kraken", "coinbase"} == CcxtExchangeAdapter.SUPPORTED


def test_unknown_exchange_is_rejected_before_credentials():
    with pytest.raises(ValueError, match="UNSUPPORTED_EXCHANGE"):
        CcxtExchangeAdapter("unknown", StaticCredentials(), sandbox=True)


def test_fill_event_normalizes_exchange_response():
    fill = FillEvent.from_exchange_response(
        execution_id="exec-1",
        exchange="binance",
        requested_quantity=Decimal("0.001"),
        response={
            "id": "123",
            "symbol": "BTC/USDT",
            "side": "buy",
            "filled": "0.001",
            "average": "60000",
            "status": "filled",
            "fee": {"cost": "0.06", "currency": "USDT"},
        },
    )
    assert fill.exchange_order_id == "123"
    assert fill.executed_quantity == Decimal("0.001")
    assert fill.average_price == Decimal("60000")


def test_reconciliation_requires_exact_fill_for_reconciled():
    fill = FillEvent(
        "exec-1", "binance", "123", "BTC/USDT", "buy",
        Decimal("0.001"), Decimal("0.001"), Decimal("60000"),
        Decimal("0.06"), "USDT", "filled", {}
    )
    result = Reconciler().reconcile(Decimal("0.001"), fill)
    assert result.status == "RECONCILED"


def test_reconciliation_does_not_claim_success_for_partial():
    fill = FillEvent(
        "exec-2", "kraken", "456", "BTC/USD", "buy",
        Decimal("0.001"), Decimal("0.0004"), Decimal("60000"),
        Decimal("0.024"), "USD", "open", {}
    )
    result = Reconciler().reconcile(Decimal("0.001"), fill)
    assert result.status == "PARTIAL"
