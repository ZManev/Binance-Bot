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
    fees: tuple[tuple[str | None, Decimal], ...] = ()

    @classmethod
    def from_exchange_response(cls, execution_id: str, exchange: str, response: dict[str, Any], requested_quantity: Decimal) -> "FillEvent":
        fee_list = [f for f in (response.get("fees") or []) if f and f.get("cost") is not None]
        fee = response.get("fee") or {}
        if not fee_list and fee.get("cost") is not None:
            fee_list = [fee]
        totals: dict[str | None, Decimal] = {}
        for f in fee_list:
            totals[f.get("currency")] = totals.get(f.get("currency"), Decimal("0")) + Decimal(str(f["cost"]))
        fees = tuple(totals.items())
        if len(fees) == 1:
            fee_currency, fee_cost = fees[0]
        else:
            # Zero or multiple currencies: no single scalar fee; see `fees`.
            fee_currency, fee_cost = None, None
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
            fee_cost=fee_cost,
            fee_currency=fee_currency,
            status=str(response.get("status", "unknown")),
            raw=response,
            fees=fees,
        )
