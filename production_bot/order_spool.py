from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .gate import ExecutionBlocked, ExecutionGate, PreSubmitRejection
from .models import AuthorizedOrder, RiskApproval, TradeProposal

log = logging.getLogger("order_spool")


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed


def _dec(value: Any) -> Decimal:
    # NaN/Infinity are malformed input, not an uncertain exchange outcome.
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("NON_FINITE_DECIMAL")
    return parsed


def parse_order(data: dict[str, Any]) -> AuthorizedOrder:
    p = data["proposal"]
    a = data["approval"]
    proposal = TradeProposal(
        order_id=p["order_id"],
        account_id=p["account_id"],
        symbol=p["symbol"],
        side=p["side"],
        quantity=_dec(p["quantity"]),
        order_type=p.get("order_type", "market"),
        price=_dec(p["price"]) if p.get("price") is not None else None,
        strategy_id=p.get("strategy_id", "unknown"),
        strategy_version=p.get("strategy_version", "unknown"),
        exchange=p.get("exchange", ""),
    )
    approval = RiskApproval(
        approval_id=a["approval_id"],
        order_id=a["order_id"],
        order_hash=a["order_hash"],
        approved_quantity=_dec(a["approved_quantity"]),
        approved_notional=_dec(a["approved_notional"]),
        policy_version=a["policy_version"],
        issued_at=_dt(a["issued_at"]),
        expires_at=_dt(a["expires_at"]),
        nonce=a["nonce"],
        signature=a["signature"],
    )
    return AuthorizedOrder(proposal, approval)


def publish_order(spool_dir: str, name: str, payload: dict[str, Any]) -> Path:
    """Atomically publish an order into incoming/.

    Writes to a hidden temp name the consumer never globs, fsyncs, then renames
    into place, so the consumer only ever sees complete files. All producers must
    use this (or the same write-temp-then-rename protocol).
    """
    if not name.endswith(".json") or "/" in name or name.startswith("."):
        raise ValueError("INVALID_ORDER_FILENAME")
    incoming = Path(spool_dir) / "incoming"
    tmp = incoming / f".{uuid4().hex}.{name}.tmp"
    final = incoming / name
    try:
        with open(tmp, "x") as fh:
            fh.write(json.dumps(payload))
            fh.flush()
            os.fsync(fh.fileno())
        # link() never replaces an existing file: a pending order with the same
        # name raises FileExistsError instead of being silently overwritten.
        os.link(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    return final


class SpoolConsumer:
    """Claims files from incoming/ and moves each to done/, rejected/ or unknown/.

    Producers must publish atomically (see publish_order): only complete *.json
    files may appear in incoming/. Partial writes would be rejected as malformed.

    unknown/ means an exchange request may have been sent; never auto-retry those.
    """

    BUCKETS = ("incoming", "processing", "done", "rejected", "unknown")

    def __init__(self, gate: ExecutionGate, spool_dir: str) -> None:
        self.gate = gate
        self.root = Path(spool_dir)
        for name in self.BUCKETS:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def _finish(self, claimed: Path, original_name: str, bucket: str, result: dict[str, Any]) -> None:
        # Never overwrite an earlier order's record: on a name collision, add a unique suffix.
        stem = Path(original_name).stem
        dest_dir = self.root / bucket
        while True:
            try:
                with open(dest_dir / (stem + ".result.json"), "x") as fh:
                    fh.write(json.dumps(result, default=str))
                break
            except FileExistsError:
                stem = f"{Path(original_name).stem}.{uuid4().hex}"
        dest = dest_dir / (stem + ".json")
        if dest.exists():
            raise FileExistsError(f"SPOOL_DESTINATION_EXISTS:{dest}")
        claimed.rename(dest)

    def process_once(self, stop: Any = None) -> int:
        count = 0
        for path in sorted((self.root / "incoming").glob("*.json")):
            if stop is not None and stop.is_set():
                break  # shutting down: leave unclaimed files in incoming/
            original_name = path.name
            # Unique claim name so a reused incoming filename never replaces a file in processing/.
            claimed = self.root / "processing" / f"{uuid4().hex}.{original_name}"
            try:
                path.rename(claimed)
            except FileNotFoundError:
                continue
            count += 1
            try:
                order = parse_order(json.loads(claimed.read_text()))
            except Exception as exc:  # malformed input never reaches the gate
                self._finish(claimed, original_name, "rejected", {"error": f"MALFORMED_ORDER:{type(exc).__name__}"})
                continue
            order_id = order.proposal.order_id
            try:
                response = self.gate.execute(order)
            except (ExecutionBlocked, PreSubmitRejection) as exc:
                log.warning("order %s rejected: %s", order_id, exc)
                self._finish(claimed, original_name, "rejected", {"order_id": order_id, "error": str(exc)})
            except Exception as exc:
                # The exchange may have received the request: the reservation is kept.
                log.error("order %s outcome unknown: %s", order_id, type(exc).__name__)
                self._finish(claimed, original_name, "unknown", {"order_id": order_id, "error": type(exc).__name__})
            else:
                self._finish(claimed, original_name, "done", {"order_id": order_id, "exchange_response": response})
        return count
