from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .models import AuthorizedOrder, TradeProposal
from .security import order_hash, verify_approval


class ExecutionBlocked(Exception):
    """Raised whenever the capital boundary cannot prove authorization."""


class IdempotencyStore(Protocol):
    def seen(self, order_id: str) -> bool: ...
    def mark(self, order_id: str) -> None: ...


class KillSwitch(Protocol):
    def active(self, account_id: str, symbol: str, strategy_id: str) -> bool: ...


class ExchangeAdapter(Protocol):
    def submit(self, order: AuthorizedOrder) -> dict: ...


class SecureExecutionGate:
    """Non-bypassable execution choke point.

    This component has a Risk public key only. It cannot mint approvals and it has
    no Binance credential. Live exchange access is delegated to the adapter.
    """

    def __init__(
        self,
        adapter: ExchangeAdapter,
        idempotency: IdempotencyStore,
        kill_switch: KillSwitch,
        verification_key: Ed25519PublicKey,
    ) -> None:
        self._adapter = adapter
        self._idempotency = idempotency
        self._kill_switch = kill_switch
        self._verification_key = verification_key

    def execute(self, order: AuthorizedOrder) -> dict:
        proposal: TradeProposal = order.proposal
        approval = order.approval
        now = datetime.now(timezone.utc)

        if proposal.execution_environment != "production":
            raise ExecutionBlocked("PRODUCTION_GATE_REQUIRES_PRODUCTION_ENVIRONMENT")
        if approval.order_id != proposal.order_id:
            raise ExecutionBlocked("ORDER_ID_MISMATCH")
        if approval.order_hash != order_hash(proposal):
            raise ExecutionBlocked("ORDER_HASH_MISMATCH")
        if approval.approved_quantity != proposal.quantity:
            raise ExecutionBlocked("APPROVED_QUANTITY_MISMATCH")
        if now >= approval.expires_at:
            raise ExecutionBlocked("APPROVAL_EXPIRED")
        if self._kill_switch.active(proposal.account_id, proposal.symbol, proposal.strategy_id):
            raise ExecutionBlocked("KILL_SWITCH_ACTIVE")
        if not verify_approval(
            approval.order_hash,
            approval.policy_version,
            approval.nonce,
            approval.expires_at.isoformat(),
            approval.signature,
            self._verification_key,
        ):
            raise ExecutionBlocked("INVALID_APPROVAL_SIGNATURE")
        if self._idempotency.seen(proposal.order_id):
            raise ExecutionBlocked("DUPLICATE_ORDER")

        self._idempotency.mark(proposal.order_id)
        return self._adapter.submit(order)
