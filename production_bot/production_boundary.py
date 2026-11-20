"""Fail-closed production execution boundary primitives.

This module deliberately does not submit exchange orders. It provides the
verification, durable reservation, kill-switch and audit primitives required
before an independently reviewed adapter can be connected.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class BoundaryBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionFlags:
    live_trading: bool = False
    signing_enabled: bool = False
    order_submission_enabled: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ExecutionFlags":
        source = os.environ if env is None else env
        values = (
            source.get("LIVE_TRADING", "false"),
            source.get("SIGNING_ENABLED", "false"),
            source.get("ORDER_SUBMISSION_ENABLED", "false"),
        )
        if any(value.strip().lower() not in {"false", "0", "no", "off", ""} for value in values):
            raise BoundaryBlocked("LIVE_EXECUTION_FEATURES_MUST_REMAIN_DISABLED")
        return cls()

    def assert_simulation_only(self) -> None:
        if self.live_trading or self.signing_enabled or self.order_submission_enabled:
            raise BoundaryBlocked("SIMULATION_ONLY")


@dataclass(frozen=True)
class ApprovalClaims:
    approval_id: str
    order_id: str
    order_hash: str
    account_id: str
    exchange: str
    environment: str
    symbol: str
    side: str
    quantity: str
    approved_notional: str
    policy_version: str
    nonce: str
    issued_at: int
    expires_at: int

    def canonical(self) -> bytes:
        return json.dumps(self.__dict__, sort_keys=True, separators=(",", ":")).encode()


class ApprovalVerifier:
    """Verifies external Risk Authority signatures; contains no signing key."""

    def __init__(self, public_key_pem: bytes, max_ttl_seconds: int = 15) -> None:
        if not public_key_pem:
            raise ValueError("RISK_AUTHORITY_PUBLIC_KEY_REQUIRED")
        self._public_key_pem = public_key_pem
        self._max_ttl = max_ttl_seconds

    def verify(self, claims: ApprovalClaims, signature_hex: str, now: int | None = None) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        key = serialization.load_pem_public_key(self._public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            raise BoundaryBlocked("RISK_AUTHORITY_KEY_MUST_BE_ED25519")
        current = int(time.time()) if now is None else now
        if claims.environment != "production":
            raise BoundaryBlocked("APPROVAL_ENVIRONMENT_MISMATCH")
        if claims.issued_at > current + 2 or claims.expires_at <= current:
            raise BoundaryBlocked("APPROVAL_EXPIRED_OR_NOT_YET_VALID")
        if claims.expires_at - claims.issued_at > self._max_ttl:
            raise BoundaryBlocked("APPROVAL_TTL_EXCEEDED")
        if not claims.nonce or not claims.order_id or not claims.order_hash:
            raise BoundaryBlocked("APPROVAL_REQUIRED_CLAIMS_MISSING")
        try:
            key.verify(bytes.fromhex(signature_hex), claims.canonical())
        except Exception as exc:
            raise BoundaryBlocked("INVALID_RISK_AUTHORITY_SIGNATURE") from exc


class KillSwitch(Protocol):
    def active(self, account_id: str, symbol: str, strategy_id: str) -> bool: ...


class FileKillSwitch:
    """Fail-closed persistent switch: only an explicit RUN state unhalts execution."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def active(self, account_id: str = "", symbol: str = "", strategy_id: str = "") -> bool:
        try:
            return self.path.read_text(encoding="utf-8").strip() != "RUN"
        except OSError:
            return True


class DurableBoundaryStore:
    """SQLite atomic nonce/order reservations and tamper-evident audit chain."""

    def __init__(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(target), timeout=10, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("""CREATE TABLE IF NOT EXISTS execution_reservations (
            order_id TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE,
            order_hash TEXT NOT NULL, state TEXT NOT NULL,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        )""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS boundary_audit (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL, event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
        )""")

    def reserve(self, claims: ApprovalClaims, now: int | None = None) -> None:
        current = int(time.time()) if now is None else now
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO execution_reservations VALUES (?, ?, ?, 'RESERVED', ?, ?)",
                    (claims.order_id, claims.nonce, claims.order_hash, current, current),
                )
                self._db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._db.execute("ROLLBACK")
                raise BoundaryBlocked("ORDER_OR_APPROVAL_NONCE_REPLAY") from exc
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def transition(self, order_id: str, state: str, now: int | None = None) -> None:
        allowed = {
            "RESERVED": {"SUBMITTING", "REJECTED", "UNKNOWN"},
            "SUBMITTING": {"ACKNOWLEDGED", "UNKNOWN", "REJECTED"},
            "ACKNOWLEDGED": {"RECONCILED", "UNKNOWN"},
            "UNKNOWN": {"RECONCILED"},
            "REJECTED": set(),
            "RECONCILED": set(),
        }
        current = int(time.time()) if now is None else now
        with self._lock:
            row = self._db.execute("SELECT state FROM execution_reservations WHERE order_id=?", (order_id,)).fetchone()
            if row is None:
                raise BoundaryBlocked("RESERVATION_NOT_FOUND")
            if state not in allowed.get(row[0], set()):
                raise BoundaryBlocked("INVALID_EXECUTION_STATE_TRANSITION")
            self._db.execute(
                "UPDATE execution_reservations SET state=?, updated_at=? WHERE order_id=?",
                (state, current, order_id),
            )

    def append_audit(self, event_type: str, payload: dict[str, Any], now: int | None = None) -> str:
        current = int(time.time()) if now is None else now
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT event_hash FROM boundary_audit ORDER BY sequence DESC LIMIT 1").fetchone()
                previous = row[0] if row else "0" * 64
                sequence = self._db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM boundary_audit").fetchone()[0]
                event_id = hashlib.sha256(f"{current}:{sequence}:{event_type}".encode()).hexdigest()
                canonical = json.dumps(
                    {"event_id": event_id, "created_at": current, "event_type": event_type,
                     "payload_json": payload_json, "previous_hash": previous},
                    sort_keys=True, separators=(",", ":"),
                ).encode()
                digest = hashlib.sha256(canonical).hexdigest()
                self._db.execute(
                    "INSERT INTO boundary_audit(event_id,created_at,event_type,payload_json,previous_hash,event_hash) VALUES(?,?,?,?,?,?)",
                    (event_id, current, event_type, payload_json, previous, digest),
                )
                self._db.execute("COMMIT")
                return digest
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def verify_audit(self) -> bool:
        previous = "0" * 64
        with self._lock:
            rows = self._db.execute(
                "SELECT event_id,created_at,event_type,payload_json,previous_hash,event_hash FROM boundary_audit ORDER BY sequence"
            ).fetchall()
        for event_id, created_at, event_type, payload_json, prev, digest in rows:
            if prev != previous:
                return False
            canonical = json.dumps(
                {"event_id": event_id, "created_at": created_at, "event_type": event_type,
                 "payload_json": payload_json, "previous_hash": prev},
                sort_keys=True, separators=(",", ":"),
            ).encode()
            if hashlib.sha256(canonical).hexdigest() != digest:
                return False
            previous = digest
        return True

    def close(self) -> None:
        with self._lock:
            self._db.close()


class ProductionExecutionBoundary:
    """Fail-closed orchestration boundary. No exchange adapter is invoked."""

    def __init__(self, flags: ExecutionFlags, verifier: ApprovalVerifier,
                 store: DurableBoundaryStore, kill_switch: KillSwitch) -> None:
        flags.assert_simulation_only()
        self.flags, self.verifier, self.store, self.kill_switch = flags, verifier, store, kill_switch

    def authorize_for_simulation(self, claims: ApprovalClaims, signature_hex: str,
                                 strategy_id: str = "unknown", now: int | None = None) -> str:
        self.verifier.verify(claims, signature_hex, now)
        if self.kill_switch.active(claims.account_id, claims.symbol, strategy_id):
            raise BoundaryBlocked("KILL_SWITCH_ACTIVE")
        self.store.reserve(claims, now)
        self.store.append_audit("SIMULATION_AUTHORIZATION_ACCEPTED", {
            "approval_id": claims.approval_id, "order_id": claims.order_id,
            "order_hash": claims.order_hash, "exchange": claims.exchange,
            "environment": claims.environment, "symbol": claims.symbol,
        }, now)
        return "SIMULATION_ONLY"
