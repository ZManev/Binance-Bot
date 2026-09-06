from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .models import RiskApproval, TradeProposal, utcnow
from .security import order_hash, sign_approval


@dataclass(frozen=True)
class RiskLimits:
    max_order_notional: Decimal
    max_position_notional: Decimal
    max_daily_loss: Decimal
    approval_ttl_seconds: int = 10


class RiskRejected(Exception):
    pass


class RiskEngine:
    """Deterministic authorization layer; it has no exchange credentials."""

    def __init__(self, limits: RiskLimits, signing_key: Ed25519PrivateKey, policy_version: str = "risk-v1") -> None:
        self.limits = limits
        self.signing_key = signing_key
        self.policy_version = policy_version

    def authorize(
        self,
        proposal: TradeProposal,
        reference_price: Decimal,
        current_position_notional: Decimal,
        daily_loss: Decimal,
    ) -> RiskApproval:
        if proposal.quantity <= 0:
            raise RiskRejected("INVALID_QUANTITY")
        if proposal.order_type == "limit" and (proposal.price is None or proposal.price <= 0):
            raise RiskRejected("INVALID_LIMIT_PRICE")

        notional = proposal.quantity * (proposal.price or reference_price)
        if notional > self.limits.max_order_notional:
            raise RiskRejected("MAX_ORDER_NOTIONAL_EXCEEDED")
        if current_position_notional + notional > self.limits.max_position_notional:
            raise RiskRejected("MAX_POSITION_NOTIONAL_EXCEEDED")
        if daily_loss >= self.limits.max_daily_loss:
            raise RiskRejected("MAX_DAILY_LOSS_EXCEEDED")
        if self.limits.approval_ttl_seconds <= 0:
            raise RiskRejected("INVALID_APPROVAL_TTL")

        issued = utcnow()
        expires = issued + timedelta(seconds=self.limits.approval_ttl_seconds)
        nonce = uuid4().hex
        digest = order_hash(proposal)
        signature = sign_approval(digest, self.policy_version, nonce, expires.isoformat(), self.signing_key)
        return RiskApproval(
            approval_id=uuid4().hex,
            order_id=proposal.order_id,
            order_hash=digest,
            approved_quantity=proposal.quantity,
            approved_notional=notional,
            policy_version=self.policy_version,
            issued_at=issued,
            expires_at=expires,
            nonce=nonce,
            signature=signature,
        )
