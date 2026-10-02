from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .fills import FillEvent


@dataclass(frozen=True)
class ReconciliationResult:
    execution_id: str
    expected_quantity: Decimal
    observed_quantity: Decimal
    status: str
    reason: str


class Reconciler:
    def reconcile(self, expected_quantity: Decimal, fill: FillEvent) -> ReconciliationResult:
        observed = fill.executed_quantity
        if fill.status == "filled" and observed == expected_quantity:
            return ReconciliationResult(fill.execution_id, expected_quantity, observed, "RECONCILED", "EXACT_FILLED_QUANTITY")
        if observed > Decimal("0") and observed <= expected_quantity:
            return ReconciliationResult(fill.execution_id, expected_quantity, observed, "PARTIAL", "PARTIAL_EXECUTION")
        if fill.status in {"canceled", "rejected", "expired"}:
            return ReconciliationResult(fill.execution_id, expected_quantity, observed, "REJECTED_OR_CANCELED", fill.status.upper())
        return ReconciliationResult(fill.execution_id, expected_quantity, observed, "MISMATCH", "OBSERVED_RESULT_NOT_AUTHORIZED_STATE")
