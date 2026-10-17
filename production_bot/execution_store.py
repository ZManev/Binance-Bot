from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

from .gate import ExecutionBlocked
from .multi_exchange import ExchangeCredentials


class SqliteIdempotencyStore:
    """Persistent order-id reservations. Survives restarts."""

    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS reservations (order_id TEXT PRIMARY KEY, created_at REAL NOT NULL)")

    def seen(self, order_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM reservations WHERE order_id = ?", (order_id,)).fetchone() is not None

    def mark(self, order_id: str) -> None:
        # PRIMARY KEY makes the reservation atomic even if two workers race past seen().
        with self._lock:
            try:
                self._db.execute("INSERT INTO reservations (order_id, created_at) VALUES (?, ?)", (order_id, time.time()))
            except sqlite3.IntegrityError:
                raise ExecutionBlocked("DUPLICATE_ORDER") from None

    def release(self, order_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM reservations WHERE order_id = ?", (order_id,))

    def ping(self) -> bool:
        with self._lock:
            self._db.execute("SELECT 1").fetchone()
        return True


class FileKillSwitch:
    """Global kill switch: execution halts while the file exists."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def active(self, account_id: str, symbol: str, strategy_id: str) -> bool:
        return self.path.exists()


class EnvCredentials:
    """Reads credentials injected by the deployment. Never reads the repository .env."""

    def get(self, exchange_id: str) -> ExchangeCredentials:
        key = os.environ.get("EXCHANGE_API_KEY", "").strip()
        secret = os.environ.get("EXCHANGE_API_SECRET", "").strip()
        if not key or not secret:
            raise ValueError("EXCHANGE_CREDENTIALS_MISSING")
        return ExchangeCredentials(key, secret, os.environ.get("EXCHANGE_PASSWORD") or None)
