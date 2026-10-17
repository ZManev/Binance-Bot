"""Execution service entrypoint: spool consumer + /healthz and /readyz.

Environment (set by deployment only, never by order payloads):
  EXCHANGE_ID, EXCHANGE_API_KEY, EXCHANGE_API_SECRET, EXCHANGE_PASSWORD (optional),
  APPROVAL_SIGNING_SECRET, LIVE_TRADING (exactly "true" for live; default sandbox),
  SPOOL_DIR, STATE_DB, KILL_SWITCH_FILE, POLL_INTERVAL_SECONDS, PORT.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .execution_store import EnvCredentials, FileKillSwitch, SqliteIdempotencyStore
from .gate import ExecutionGate
from .multi_exchange import CcxtExchangeAdapter
from .order_spool import SpoolConsumer

log = logging.getLogger("execution_service")


class ServiceState:
    def __init__(self, poll_interval: float = 1.0) -> None:
        self.poll_interval = poll_interval
        self.checks = {"config": False, "adapter": False, "idempotency_store": False, "consumer": False}
        self.live = False
        self.exchange_id: str | None = None
        self.error: str | None = None
        self.last_poll: float | None = None
        self.store: SqliteIdempotencyStore | None = None
        self.kill_switch: FileKillSwitch | None = None

    def ready(self) -> bool:
        if not all(self.checks.values()) or self.last_poll is None:
            return False
        if time.time() - self.last_poll > max(10.0, self.poll_interval * 5):
            return False
        try:
            return bool(self.store and self.store.ping())
        except sqlite3.Error:
            return False

    def readiness(self) -> dict:
        ready = self.ready()
        return {
            "status": "ready" if ready else "not_ready",
            "checks": dict(self.checks),
            "exchange": self.exchange_id,
            "mode": "live" if self.live else "sandbox",
            "kill_switch_active": bool(self.kill_switch and self.kill_switch.path.exists()),
            "error": self.error,
        }


def make_handler(state: ServiceState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/healthz":
                code, body = 200, {"status": "ok"}
            elif self.path == "/readyz":
                body = state.readiness()
                code = 200 if body["status"] == "ready" else 503
            else:
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    return Handler


def build(state: ServiceState, env=os.environ) -> SpoolConsumer:
    exchange_id = env.get("EXCHANGE_ID", "").strip()
    signing_secret = env.get("APPROVAL_SIGNING_SECRET", "").encode()
    if not exchange_id or not signing_secret:
        raise ValueError("EXCHANGE_ID_AND_APPROVAL_SIGNING_SECRET_REQUIRED")
    # Fail closed: anything other than exactly "true" stays on sandbox endpoints.
    live = env.get("LIVE_TRADING", "") == "true"
    state.exchange_id, state.live = exchange_id, live
    state.checks["config"] = True

    adapter = CcxtExchangeAdapter(exchange_id, EnvCredentials(), signing_secret, sandbox=not live)
    state.checks["adapter"] = True

    state.store = SqliteIdempotencyStore(env.get("STATE_DB", "/var/lib/trading/idempotency.sqlite3"))
    state.checks["idempotency_store"] = True

    state.kill_switch = FileKillSwitch(env.get("KILL_SWITCH_FILE", "/var/lib/trading/KILL"))
    gate = ExecutionGate(adapter, state.store, state.kill_switch, signing_secret)
    consumer = SpoolConsumer(gate, env.get("SPOOL_DIR", "/var/lib/trading/spool"))
    state.checks["consumer"] = True
    return consumer


def run_loop(state: ServiceState, consumer: SpoolConsumer, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            consumer.process_once()
            state.last_poll = time.time()
        except Exception as exc:  # keep serving health; readiness goes stale
            state.error = type(exc).__name__
            log.exception("spool poll failed")
        stop.wait(state.poll_interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    state = ServiceState(float(os.environ.get("POLL_INTERVAL_SECONDS", "1")))
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        consumer = build(state)
    except Exception as exc:
        # Stay up so /readyz reports why; never execute without a full build.
        state.error = f"{type(exc).__name__}:{exc}"
        log.error("startup failed: %s", state.error)
        threading.Event().wait()
        return
    log.info("execution service started exchange=%s mode=%s", state.exchange_id, "live" if state.live else "sandbox")
    run_loop(state, consumer, threading.Event())


if __name__ == "__main__":
    main()
