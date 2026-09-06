from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any


class AuditChain:
    """Append-only in-memory reference implementation; persist behind a write-only audit service in production."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._last_hash = "0" * 64

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "event_id": hashlib.sha256(f"{datetime.now(timezone.utc).timestamp()}:{len(self._events)}".encode()).hexdigest(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
            "previous_hash": self._last_hash,
        }
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str).encode()
        event["event_hash"] = hashlib.sha256(canonical).hexdigest()
        self._last_hash = event["event_hash"]
        self._events.append(event)
        return event

    def verify(self) -> bool:
        previous = "0" * 64
        for event in self._events:
            if event["previous_hash"] != previous:
                return False
            candidate = dict(event)
            event_hash = candidate.pop("event_hash")
            canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":"), default=str).encode()
            if hashlib.sha256(canonical).hexdigest() != event_hash:
                return False
            previous = event_hash
        return True
