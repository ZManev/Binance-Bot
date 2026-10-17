from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from .fills import FillEvent
from .gate import ExecutionGate, PreSubmitRejection
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


@pytest.mark.parametrize("status,observed,expected_status,reason", [
    ("canceled", "1", "FILLED_TERMINAL", "CANCELED_AFTER_FULL_FILL"),
    ("canceled", "1.5", "MISMATCH", "OVERFILL"),
    ("closed", "1.5", "MISMATCH", "OVERFILL"),
])
def test_terminal_full_fill_and_overfill(status, observed, expected_status, reason):
    fill = FillEvent(
        "exec-6", "kraken", "459", "BTC/USD", "buy",
        Decimal("1"), Decimal(observed), None, None, None, status, {}
    )
    result = Reconciler().reconcile(Decimal("1"), fill)
    assert result.status == expected_status
    assert result.reason == reason


def test_canceled_unfilled_order_is_rejected_or_canceled():
    fill = FillEvent(
        "exec-5", "kraken", "458", "BTC/USD", "buy",
        Decimal("1"), Decimal("0"), None, None, None, "canceled", {}
    )
    result = Reconciler().reconcile(Decimal("1"), fill)
    assert result.status == "REJECTED_OR_CANCELED"
    assert result.reason == "CANCELED"


class FakeExchange:
    def __init__(self, ask=50000, bid=49990):
        self.calls = []
        self.ticker = {"ask": ask, "bid": bid, "last": ask}

    def fetch_ticker(self, symbol):
        return self.ticker

    def create_order(self, *args):
        self.calls.append(args)
        return {"id": "x"}


def _adapter(kill_switch=None, **fake):
    adapter = CcxtExchangeAdapter("binance", StaticCredentials(), SECRET, kill_switch=kill_switch)
    adapter.exchange = FakeExchange(**fake)
    return adapter


def _order(
    expires_delta=timedelta(minutes=1), signature=None, approved_quantity=Decimal("0.001"),
    exchange="binance", order_type="market", price=None, notional=Decimal("60"),
    approval_order_id="o1", approval_hash=None, signed_notional=None,
):
    proposal = TradeProposal("o1", "acct", "BTC/USDT", "buy", Decimal("0.001"), order_type, price, exchange=exchange)
    digest = order_hash(proposal)
    expires_at = datetime.now(timezone.utc) + expires_delta
    # signed_notional lets a test sign one notional and store another (tampering).
    sig = signature or sign_approval(
        digest, "v1", "n1", expires_at.isoformat(),
        notional if signed_notional is None else signed_notional, SECRET,
    )
    approval = RiskApproval(
        "a1", approval_order_id, approval_hash or digest, approved_quantity, notional, "v1",
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
    ({"signed_notional": Decimal("60"), "notional": Decimal("1000000")}, "INVALID_APPROVAL_SIGNATURE"),
    ({"signed_notional": Decimal("60"), "notional": Decimal("60.000000000000000000000000000001")}, "INVALID_APPROVAL_SIGNATURE"),
    ({"approved_quantity": Decimal("0.002")}, "APPROVED_QUANTITY_MISMATCH"),
    ({"approval_order_id": "other"}, "ORDER_ID_MISMATCH"),
    ({"approval_hash": "0" * 64}, "ORDER_HASH_MISMATCH"),
    ({"exchange": "kraken"}, "EXCHANGE_MISMATCH"),
    ({"exchange": ""}, "EXCHANGE_MISMATCH"),
    ({"notional": Decimal("10")}, "APPROVED_NOTIONAL_EXCEEDED"),
    ({"order_type": "limit", "price": Decimal("70000")}, "APPROVED_NOTIONAL_EXCEEDED"),
])
def test_adapter_rejects_invalid_approval(kwargs, reason):
    adapter = _adapter()
    with pytest.raises(UnauthorizedOrder, match=reason):
        adapter.submit(_order(**kwargs))
    assert adapter.exchange.calls == []


def test_adapter_submits_priced_limit_order():
    adapter = _adapter()
    adapter.submit(_order(order_type="limit", price=Decimal("55000")))
    assert adapter.exchange.calls == [("BTC/USDT", "limit", "buy", 0.001, 55000.0)]


def test_limit_without_price_is_pre_submit_rejection():
    adapter = _adapter()
    with pytest.raises(PreSubmitRejection, match="LIMIT_ORDER_REQUIRES_PRICE"):
        adapter.submit(_order(order_type="limit", price=None))
    assert adapter.exchange.calls == []


def test_market_order_without_quote_is_rejected():
    adapter = _adapter(ask=None, bid=None)
    adapter.exchange.ticker["last"] = None
    with pytest.raises(PreSubmitRejection, match="NO_REFERENCE_PRICE"):
        adapter.submit(_order())
    assert adapter.exchange.calls == []


def test_quote_fetch_failure_is_pre_submit_rejection():
    adapter = _adapter()

    def boom(symbol):
        raise ConnectionError("network down")

    adapter.exchange.fetch_ticker = boom
    with pytest.raises(PreSubmitRejection, match="REFERENCE_PRICE_UNAVAILABLE:ConnectionError"):
        adapter.submit(_order())
    assert adapter.exchange.calls == []


def test_adapter_honours_kill_switch_on_direct_call():
    class On:
        def active(self, *a): return True

    adapter = _adapter(kill_switch=On())
    with pytest.raises(UnauthorizedOrder, match="KILL_SWITCH_ACTIVE"):
        adapter.submit(_order())
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


@pytest.mark.parametrize("status", ["filled", "closed"])
def test_underfilled_order_reported_filled_is_not_reconciled(status):
    fill = FillEvent(
        "exec-7", "binance", "460", "BTC/USDT", "buy",
        Decimal("1"), Decimal("0.4"), None, None, None, status, {}
    )
    result = Reconciler().reconcile(Decimal("1"), fill)
    assert result.status == "PARTIAL"
    assert result.reason == "PARTIAL_EXECUTION"
