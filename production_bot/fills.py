from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FillEvent:
    execution_id: str
    exchange: str
    exchange_order_id: str
    symbol: str
    side: str
    requested_quantity: Decimal
    executed_quantity: Decimal
    average_price: Decimal | None
    fee_cost: Decimal | None
    fee_currency: str | None
    status: str
    raw: dict[str, Any]

    @classmethod
    def from_exchange_response(cls, execution_id: str, exchange: str, response: dict[str, Any], requested_quantity: Decimal) -> "FillEvent":
        fee = response.get("fee") or {}
        average = response.get("average")
        return cls(
            execution_id=execution_id,
            exchange=exchange,
            exchange_order_id=str(response.get("id", "")),
            symbol=str(response.get("symbol", "")),
            side=str(response.get("side", "")),
            requested_quantity=requested_quantity,
            executed_quantity=Decimal(str(response.get("filled") or 0)),
            average_price=Decimal(str(average)) if average is not None else None,
            fee_cost=Decimal(str(fee["cost"])) if fee.get("cost") is not None else None,
            fee_currency=fee.get("currency"),
            status=str(response.get("status", "unknown")),
            raw=response,
        )
