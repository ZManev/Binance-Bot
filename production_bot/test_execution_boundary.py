from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .execution_gate import ExecutionBlocked, SecureExecutionGate
from .models import AuthorizedOrder, TradeProposal, utcnow
from .risk import RiskEngine, RiskLimits
from .execution_state import ExecutionRecord, ExecutionState, MemoryExecutionStateStore


class StaticKill:
    def __init__(self, active=False):
        self.is_active = active

    def active(self, account_id, symbol, strategy_id):
        return self.is_active


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def submit(self, order):
        self.calls.append(order)
        return {"status": "accepted"}


def make_proposal(environment="production"):
    return TradeProposal(
        order_id="o1",
        account_id="prod-spot",
        symbol="BTC/USDT",
        side="buy",
        quantity=Decimal("0.001"),
        order_type="market",
        strategy_id="s1",
        strategy_version="v1",
        execution_environment=environment,
        client_order_id="cid-o1",
    )


def make_boundary():
    private = Ed25519PrivateKey.generate()
    engine = RiskEngine(
        RiskLimits(Decimal("1000"), Decimal("5000"), Decimal("250")),
        private,
    )
    adapter = FakeAdapter()
    state = MemoryExecutionStateStore()
    gate = SecureExecutionGate(adapter, state, StaticKill(), private.public_key())
    return engine, gate, adapter, state


def test_secure_gate_requires_production_environment():
    engine, gate, adapter, _ = make_boundary()
    proposal = make_proposal("testnet")
    approval = engine.authorize(proposal, Decimal("60000"), Decimal("0"), Decimal("0"))
    with pytest.raises(ExecutionBlocked, match="PRODUCTION_GATE"):
        gate.execute(AuthorizedOrder(proposal, approval))
    assert adapter.calls == []


def test_secure_gate_accepts_only_valid_ed25519_approval():
    engine, gate, adapter, state = make_boundary()
    proposal = make_proposal()
    approval = engine.authorize(proposal, Decimal("60000"), Decimal("0"), Decimal("0"))
    result = gate.execute(AuthorizedOrder(proposal, approval))
    assert result["status"] == "accepted"
    assert len(adapter.calls) == 1
    assert state.get("o1") is None


def test_secure_gate_rejects_forged_signature():
    engine, gate, adapter, _ = make_boundary()
    proposal = make_proposal()
    approval = engine.authorize(proposal, Decimal("60000"), Decimal("0"), Decimal("0"))
    forged = approval.__class__(
        approval.approval_id,
        approval.order_id,
        approval.order_hash,
        approval.approved_quantity,
        approval.approved_notional,
        approval.policy_version,
        approval.issued_at,
        approval.expires_at,
        approval.nonce,
        Ed25519PrivateKey.generate().sign(b"forged").hex(),
    )
    with pytest.raises(ExecutionBlocked, match="INVALID_APPROVAL_SIGNATURE"):
        gate.execute(AuthorizedOrder(proposal, forged))
    assert adapter.calls == []


def test_state_store_rejects_double_reservation():
    store = MemoryExecutionStateStore()
    record = ExecutionRecord("o1", "cid-o1", ExecutionState.PENDING)
    assert store.reserve(record)
    assert not store.reserve(record)
    assert store.get("o1").state == ExecutionState.PENDING


def test_state_store_requires_expected_state_for_transition():
    store = MemoryExecutionStateStore()
    store.reserve(ExecutionRecord("o1", "cid-o1", ExecutionState.PENDING))
    with pytest.raises(Exception, match="INVALID_EXECUTION_STATE_TRANSITION"):
        store.transition("o1", ExecutionState.SUBMITTING, ExecutionState.SUBMITTED)
