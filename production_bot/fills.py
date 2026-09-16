from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

Side = Literal["buy", "sell"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FillEvent:
    execution_id: str
    order_id: str
    client_order_id: str | None
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_asset: str | None
    timestamp: datetime
    raw: dict[str, Any]

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.price


def fill_from_ccxt_trade(order: dict[str, Any], trade: dict[str, Any]) -> FillEvent:
    fee = trade.get("fee") or {}
    timestamp_ms = trade.get("timestamp") or order.get("timestamp")
    timestamp = (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        if timestamp_ms is not None
        else utcnow()
    )
    return FillEvent(
        execution_id=str(trade.get("id") or f"{order.get('id')}:{timestamp_ms}"),
        order_id=str(order.get("id") or trade.get("order") or ""),
        client_order_id=order.get("clientOrderId"),
        symbol=str(trade.get("symbol") or order.get("symbol") or ""),
        side=trade.get("side") or order.get("side"),
        quantity=Decimal(str(trade.get("amount") or 0)),
        price=Decimal(str(trade.get("price") or order.get("average") or 0)),
        fee=Decimal(str(fee.get("cost") or 0)),
        fee_asset=fee.get("currency"),
        timestamp=timestamp,
        raw=trade,
    )
