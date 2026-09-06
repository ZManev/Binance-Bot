from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
ExecutionEnvironment = Literal["testnet", "production"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TradeProposal:
    order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType = "market"
    price: Decimal | None = None
    strategy_id: str = "unknown"
    strategy_version: str = "unknown"
    execution_environment: ExecutionEnvironment = "testnet"
    client_order_id: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class RiskApproval:
    approval_id: str
    order_id: str
    order_hash: str
    approved_quantity: Decimal
    approved_notional: Decimal
    policy_version: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    signature: str


@dataclass(frozen=True)
class AuthorizedOrder:
    proposal: TradeProposal
    approval: RiskApproval
