from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .models import AuthorizedOrder, TradeProposal
from .security import order_hash, verify_approval


class ExecutionBlocked(Exception):
    pass


class IdempotencyStore(Protocol):
    def seen(self, order_id: str) -> bool: ...
    def mark(self, order_id: str) -> None: ...


class KillSwitch(Protocol):
    def active(self, account_id: str, symbol: str, strategy_id: str) -> bool: ...


class ExchangeAdapter(Protocol):
    def submit(self, order: AuthorizedOrder) -> dict: ...


class ExecutionGate:
    """Only accepts an order carrying a valid, unexpired RiskApproval."""

    def __init__(self, adapter: ExchangeAdapter, idempotency: IdempotencyStore, kill_switch: KillSwitch, signing_secret: bytes) -> None:
        self.adapter = adapter
        self.idempotency = idempotency
        self.kill_switch = kill_switch
        self.signing_secret = signing_secret

    def execute(self, order: AuthorizedOrder) -> dict:
        proposal: TradeProposal = order.proposal
        approval = order.approval
        now = datetime.now(timezone.utc)

        if approval.order_id != proposal.order_id:
            raise ExecutionBlocked("ORDER_ID_MISMATCH")
        if approval.order_hash != order_hash(proposal):
            raise ExecutionBlocked("ORDER_HASH_MISMATCH")
        if now >= approval.expires_at:
            raise ExecutionBlocked("APPROVAL_EXPIRED")
        if approval.approved_quantity != proposal.quantity:
            raise ExecutionBlocked("APPROVED_QUANTITY_MISMATCH")
        if self.kill_switch.active(proposal.account_id, proposal.symbol, proposal.strategy_id):
            raise ExecutionBlocked("KILL_SWITCH_ACTIVE")
        if not verify_approval(
            approval.order_hash,
            approval.policy_version,
            approval.nonce,
            approval.expires_at.isoformat(),
            approval.signature,
            self.signing_secret,
        ):
            raise ExecutionBlocked("INVALID_APPROVAL_SIGNATURE")
        if self.idempotency.seen(proposal.order_id):
            raise ExecutionBlocked("DUPLICATE_ORDER")

        self.idempotency.mark(proposal.order_id)
        return self.adapter.submit(order)
