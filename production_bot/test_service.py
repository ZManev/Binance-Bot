import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .execution_store import FileKillSwitch, SqliteIdempotencyStore
from .gate import ExecutionGate
from .order_spool import SpoolConsumer
from .security import order_hash, sign_approval
from .service import ServiceState, build
from .models import TradeProposal

SECRET = b"spool-secret"


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def submit(self, order):
        self.calls.append(order.proposal.order_id)
        return {"id": "ex-1", "status": "closed"}


class Kill:
    def active(self, *a):
        return False


def _payload(order_id="o1", expires_delta=timedelta(minutes=1)):
    proposal = TradeProposal(order_id, "acct", "BTC/USDT", "buy", Decimal("0.001"), exchange="binance")
    digest = order_hash(proposal)
    expires_at = (datetime.now(timezone.utc) + expires_delta).isoformat()
    return {
        "proposal": {
            "order_id": order_id, "account_id": "acct", "symbol": "BTC/USDT", "side": "buy",
            "quantity": "0.001", "exchange": "binance",
        },
        "approval": {
            "approval_id": "a1", "order_id": order_id, "order_hash": digest,
            "approved_quantity": "0.001", "approved_notional": "60", "policy_version": "v1",
            "issued_at": datetime.now(timezone.utc).isoformat(), "expires_at": expires_at,
            "nonce": "n1", "signature": sign_approval(digest, "v1", "n1", expires_at, SECRET),
        },
    }


def _consumer(tmp_path, kill=None):
    adapter = FakeAdapter()
    store = SqliteIdempotencyStore(str(tmp_path / "db.sqlite3"))
    gate = ExecutionGate(adapter, store, kill or Kill(), SECRET)
    return SpoolConsumer(gate, str(tmp_path / "spool")), adapter


def _drop(consumer, name, payload):
    (consumer.root / "incoming" / name).write_text(json.dumps(payload))


def test_valid_order_is_executed_once(tmp_path):
    consumer, adapter = _consumer(tmp_path)
    _drop(consumer, "a.json", _payload())
    _drop(consumer, "b.json", _payload())  # same order_id
    consumer.process_once()
    assert adapter.calls == ["o1"]
    assert (consumer.root / "done" / "a.json").exists()
    assert (consumer.root / "rejected" / "b.json").exists()


def test_idempotency_survives_restart(tmp_path):
    consumer, _ = _consumer(tmp_path)
    _drop(consumer, "a.json", _payload())
    consumer.process_once()
    consumer2, adapter2 = _consumer(tmp_path)
    _drop(consumer2, "c.json", _payload())
    consumer2.process_once()
    assert adapter2.calls == []


def test_expired_and_malformed_orders_are_rejected(tmp_path):
    consumer, adapter = _consumer(tmp_path)
    _drop(consumer, "a.json", _payload(expires_delta=timedelta(seconds=-1)))
    (consumer.root / "incoming" / "b.json").write_text("{not json")
    consumer.process_once()
    assert adapter.calls == []
    assert (consumer.root / "rejected" / "a.json").exists()
    assert (consumer.root / "rejected" / "b.json").exists()


def test_kill_switch_file_blocks_execution(tmp_path):
    flag = tmp_path / "KILL"
    flag.write_text("")
    consumer, adapter = _consumer(tmp_path, FileKillSwitch(str(flag)))
    _drop(consumer, "a.json", _payload())
    consumer.process_once()
    assert adapter.calls == []


def test_build_fails_closed_without_signing_secret(tmp_path):
    state = ServiceState()
    try:
        build(state, {"EXCHANGE_ID": "binance"})
    except ValueError:
        pass
    assert not state.ready()


def test_build_defaults_to_sandbox_and_becomes_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("EXCHANGE_API_KEY", "k")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "s")
    env = {
        "EXCHANGE_ID": "binance", "APPROVAL_SIGNING_SECRET": "x", "LIVE_TRADING": "TRUE",
        "STATE_DB": str(tmp_path / "db.sqlite3"), "SPOOL_DIR": str(tmp_path / "spool"),
        "KILL_SWITCH_FILE": str(tmp_path / "KILL"),
    }
    state = ServiceState()
    build(state, env)
    assert state.live is False  # only exactly "true" enables live
    assert not state.ready()  # no successful poll yet
    state.last_poll = time.time()
    assert state.ready()
