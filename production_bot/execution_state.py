from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ExecutionState(StrEnum):
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ExecutionRecord:
    order_id: str
    client_order_id: str
    state: ExecutionState
    exchange_order_id: str | None = None
    last_error_code: str | None = None


class ExecutionStateStore(Protocol):
    def get(self, order_id: str) -> ExecutionRecord | None: ...
    def reserve(self, record: ExecutionRecord) -> bool: ...
    def transition(self, order_id: str, expected: ExecutionState, new: ExecutionState, *, exchange_order_id: str | None = None, error_code: str | None = None) -> None: ...


class ExecutionStateError(Exception):
    pass


class MemoryExecutionStateStore:
    """Reference state store used by unit tests; production must be durable."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}

    def get(self, order_id: str) -> ExecutionRecord | None:
        return self._records.get(order_id)

    def reserve(self, record: ExecutionRecord) -> bool:
        if record.order_id in self._records:
            return False
        self._records[record.order_id] = record
        return True

    def transition(self, order_id: str, expected: ExecutionState, new: ExecutionState, *, exchange_order_id: str | None = None, error_code: str | None = None) -> None:
        current = self._records.get(order_id)
        if current is None or current.state != expected:
            raise ExecutionStateError("INVALID_EXECUTION_STATE_TRANSITION")
        self._records[order_id] = ExecutionRecord(order_id, current.client_order_id, new, exchange_order_id, error_code)
