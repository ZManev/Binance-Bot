from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class ReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconciliationResult:
    consistent: bool
    local_order_id: str
    exchange_order_id: str | None
    exchange_status: str | None
    local_quantity: Decimal
    exchange_filled: Decimal
    reason: str | None = None


def reconcile_order(local_order_id: str, local_quantity: Decimal, exchange_order: dict[str, Any]) -> ReconciliationResult:
    exchange_id = exchange_order.get("id")
    status = exchange_order.get("status")
    filled = Decimal(str(exchange_order.get("filled") or 0))
    if not exchange_id:
        return ReconciliationResult(False, local_order_id, None, status, local_quantity, filled, "MISSING_EXCHANGE_ORDER_ID")
    if filled < 0 or filled > local_quantity:
        return ReconciliationResult(False, local_order_id, str(exchange_id), status, local_quantity, filled, "INVALID_FILLED_QUANTITY")
    return ReconciliationResult(True, local_order_id, str(exchange_id), status, local_quantity, filled)
