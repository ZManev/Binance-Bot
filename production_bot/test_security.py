from datetime import timedelta
from decimal import Decimal

import pytest

from .audit import AuditChain
from .gate import ExecutionBlocked, ExecutionGate
from .models import AuthorizedOrder, RiskApproval, TradeProposal, utcnow
from .risk import RiskEngine, RiskLimits, RiskRejected
from .security import order_hash, sign_approval


class MemoryIdempotency:
    def __init__(self): self.ids = set()
    def seen(self, order_id): return order_id in self.ids
    def mark(self, order_id): self.ids.add(order_id)


class StaticKill:
    def __init__(self, active=False): self.is_active = active
    def active(self, account_id, symbol, strategy_id): return self.is_active


class FakeAdapter:
    def __init__(self): self.calls = []
    def submit(self, order):
        self.calls.append(order)
        return {"status": "accepted"}


SECRET = b"test-signing-secret"


def proposal():
    return TradeProposal("o1", "a1", "BTC/USDT", "buy", Decimal("0.001"), "market", None, "s1", "v1")


def test_risk_approves_with_expiry_and_exact_hash():
    engine = RiskEngine(RiskLimits(Decimal("1000"), Decimal("5000"), Decimal("250")), SECRET)
    approval = engine.authorize(proposal(), Decimal("60000"), Decimal("0"), Decimal("0"))
    assert approval.order_hash == order_hash(proposal())
    assert approval.expires_at > approval.issued_at


def test_risk_rejects_excessive_order():
    engine = RiskEngine(RiskLimits(Decimal("10"), Decimal("5000"), Decimal("250")), SECRET)
    with pytest.raises(RiskRejected):
        engine.authorize(proposal(), Decimal("60000"), Decimal("0"), Decimal("0"))


def make_gate():
    adapter = FakeAdapter()
    return ExecutionGate(adapter, MemoryIdempotency(), StaticKill(), SECRET), adapter


def test_gate_executes_valid_authorization():
    gate, adapter = make_gate()
    engine = RiskEngine(RiskLimits(Decimal("1000"), Decimal("5000"), Decimal("250")), SECRET)
    p = proposal()
    a = engine.authorize(p, Decimal("60000"), Decimal("0"), Decimal("0"))
    result = gate.execute(AuthorizedOrder(p, a))
    assert result["status"] == "accepted"
    assert len(adapter.calls) == 1


def test_gate_rejects_tampered_quantity():
    gate, adapter = make_gate()
    engine = RiskEngine(RiskLimits(Decimal("1000"), Decimal("5000"), Decimal("250")), SECRET)
    p = proposal()
    a = engine.authorize(p, Decimal("60000"), Decimal("0"), Decimal("0"))
    tampered = TradeProposal(p.order_id, p.account_id, p.symbol, p.side, Decimal("1"), p.order_type, p.price, p.strategy_id, p.strategy_version)
    with pytest.raises(ExecutionBlocked, match="ORDER_HASH_MISMATCH"):
        gate.execute(AuthorizedOrder(tampered, a))
    assert adapter.calls == []


def test_gate_rejects_expired_approval():
    gate, adapter = make_gate()
    p = proposal()
    issued = utcnow() - timedelta(seconds=20)
    expires = utcnow() - timedelta(seconds=10)
    digest = order_hash(p)
    nonce = "nonce"
    signature = sign_approval(digest, "risk-v1", nonce, expires.isoformat(), SECRET)
    a = RiskApproval("a1", p.order_id, digest, p.quantity, Decimal("60"), "risk-v1", issued, expires, nonce, signature)
    with pytest.raises(ExecutionBlocked, match="APPROVAL_EXPIRED"):
        gate.execute(AuthorizedOrder(p, a))


def test_gate_rejects_kill_switch():
    adapter = FakeAdapter()
    gate = ExecutionGate(adapter, MemoryIdempotency(), StaticKill(True), SECRET)
    engine = RiskEngine(RiskLimits(Decimal("1000"), Decimal("5000"), Decimal("250")), SECRET)
    p = proposal()
    a = engine.authorize(p, Decimal("60000"), Decimal("0"), Decimal("0"))
    with pytest.raises(ExecutionBlocked, match="KILL_SWITCH_ACTIVE"):
        gate.execute(AuthorizedOrder(p, a))
    assert adapter.calls == []


def test_audit_chain_detects_tampering():
    audit = AuditChain()
    audit.append("RISK_APPROVED", {"order_id": "o1"})
    audit.append("EXECUTION", {"order_id": "o1"})
    assert audit.verify()
    audit._events[0]["payload"]["order_id"] = "tampered"
    assert not audit.verify()
