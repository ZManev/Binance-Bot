from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from .fills import FillEvent
from .gate import ExecutionGate
from .models import AuthorizedOrder, RiskApproval, TradeProposal
from .multi_exchange import CcxtExchangeAdapter, ExchangeCredentials, UnauthorizedOrder
from .reconciliation import Reconciler
from .security import order_hash, sign_approval

SECRET = b"test-signing-secret"


class StaticCredentials:
    def get(self, exchange_id):
        return ExchangeCredentials("key", "secret")


def test_supported_exchanges_are_explicit():
    assert {"binance", "kraken", "coinbase"} == CcxtExchangeAdapter.SUPPORTED


def test_unknown_exchange_is_rejected_before_credentials():
    with pytest.raises(ValueError, match="UNSUPPORTED_EXCHANGE"):
        CcxtExchangeAdapter("unknown", StaticCredentials(), b"secret", sandbox=True)


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


def test_fill_event_reads_fee_list():
    fill = FillEvent.from_exchange_response(
        "exec-3", "coinbase",
        {"id": "9", "filled": "1", "status": "closed", "fees": [{"cost": 0.1, "currency": "USD"}]},
        Decimal("1"),
    )
    assert fill.fee_cost == Decimal("0.1")
    assert fill.fee_currency == "USD"


def test_canceled_partial_fill_is_terminal():
    fill = FillEvent(
        "exec-4", "kraken", "457", "BTC/USD", "buy",
        Decimal("1"), Decimal("0.4"), None, None, None, "canceled", {}
    )
    result = Reconciler().reconcile(Decimal("1"), fill)
    assert result.status == "PARTIAL_TERMINAL"
    assert result.reason == "CANCELED_AFTER_PARTIAL_FILL"
    assert result.observed_quantity == Decimal("0.4")


def test_canceled_unfilled_order_is_rejected_or_canceled():
    fill = FillEvent(
        "exec-5", "kraken", "458", "BTC/USD", "buy",
        Decimal("1"), Decimal("0"), None, None, None, "canceled", {}
    )
    result = Reconciler().reconcile(Decimal("1"), fill)
    assert result.status == "REJECTED_OR_CANCELED"
    assert result.reason == "CANCELED"


class FakeExchange:
    def __init__(self):
        self.calls = []

    def create_order(self, *args):
        self.calls.append(args)
        return {"id": "x"}


def _adapter():
    adapter = CcxtExchangeAdapter("binance", StaticCredentials(), SECRET)
    adapter.exchange = FakeExchange()
    return adapter


def _order(expires_delta=timedelta(minutes=1), signature=None, approved_quantity=Decimal("0.001")):
    proposal = TradeProposal("o1", "acct", "BTC/USDT", "buy", Decimal("0.001"))
    digest = order_hash(proposal)
    expires_at = datetime.now(timezone.utc) + expires_delta
    sig = signature or sign_approval(digest, "v1", "n1", expires_at.isoformat(), SECRET)
    approval = RiskApproval(
        "a1", "o1", digest, approved_quantity, Decimal("60"), "v1",
        datetime.now(timezone.utc), expires_at, "n1", sig,
    )
    return AuthorizedOrder(proposal, approval)


def test_adapter_submits_valid_approval():
    adapter = _adapter()
    adapter.submit(_order())
    assert adapter.exchange.calls == [("BTC/USDT", "market", "buy", 0.001)]


@pytest.mark.parametrize("kwargs,reason", [
    ({"expires_delta": timedelta(seconds=-1)}, "APPROVAL_EXPIRED"),
    ({"signature": "bad"}, "INVALID_APPROVAL_SIGNATURE"),
    ({"approved_quantity": Decimal("0.002")}, "APPROVED_QUANTITY_MISMATCH"),
])
def test_adapter_rejects_invalid_approval(kwargs, reason):
    adapter = _adapter()
    with pytest.raises(UnauthorizedOrder, match=reason):
        adapter.submit(_order(**kwargs))
    assert adapter.exchange.calls == []


def test_gate_releases_reservation_on_pre_submit_rejection():
    class Store:
        def __init__(self): self.ids = set()
        def seen(self, i): return i in self.ids
        def mark(self, i): self.ids.add(i)
        def release(self, i): self.ids.discard(i)

    class Kill:
        def active(self, *a): return False

    class RejectingAdapter:
        def submit(self, order): raise UnauthorizedOrder("APPROVAL_EXPIRED")

    store = Store()
    gate = ExecutionGate(RejectingAdapter(), store, Kill(), SECRET)
    with pytest.raises(UnauthorizedOrder):
        gate.execute(_order())
    assert not store.seen("o1")


def test_reconciliation_does_not_claim_success_for_partial():
    fill = FillEvent(
        "exec-2", "kraken", "456", "BTC/USD", "buy",
        Decimal("0.001"), Decimal("0.0004"), Decimal("60000"),
        Decimal("0.024"), "USD", "open", {}
    )
    result = Reconciler().reconcile(Decimal("0.001"), fill)
    assert result.status == "PARTIAL"
