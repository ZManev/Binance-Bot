"""Authenticated dashboard API and execution worker lifecycle."""
from __future__ import annotations
import hmac, json, os, re, threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from .order_spool import publish_order
from .service import ServiceState, build, run_loop

SPOOL_DIR = Path(os.getenv("SPOOL_DIR", "/var/lib/trading/spool"))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_API_TOKEN", "")
worker_state = ServiceState(float(os.getenv("POLL_INTERVAL_SECONDS", "1")))
worker_stop = threading.Event()
worker_thread: threading.Thread | None = None
startup_error: str | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_thread, startup_error
    try:
        consumer = build(worker_state)
        worker_thread = threading.Thread(target=run_loop, args=(worker_state, consumer, worker_stop), daemon=True)
        worker_thread.start()
    except Exception as exc:
        startup_error = type(exc).__name__
        worker_state.error = startup_error
    yield
    worker_stop.set()
    if worker_thread:
        worker_thread.join(timeout=10)

app = FastAPI(title="Trading Execution Dashboard API", version="1.0.0", docs_url=None, redoc_url=None, lifespan=lifespan)

def require_token(authorization: str | None = Header(default=None)) -> None:
    if not DASHBOARD_TOKEN:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_TOKEN_NOT_CONFIGURED")
    if authorization is None or not hmac.compare_digest(authorization, f"Bearer {DASHBOARD_TOKEN}"):
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")

class ApprovedOrderEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal: dict[str, Any]
    approval: dict[str, Any]

@app.get("/healthz")
@app.get("/api/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "dashboard-api"}

@app.get("/readyz")
@app.get("/api/readyz")
def readyz():
    ready = worker_state.ready() and startup_error is None
    return {"status": "ready" if ready else "not_ready", "worker": worker_state.readiness(), "startup_error": startup_error}

@app.get("/api/status", dependencies=[Depends(require_token)])
def status() -> dict:
    counts = {}
    for bucket in ("incoming", "processing", "done", "rejected", "unknown"):
        directory = SPOOL_DIR / bucket
        counts[bucket] = len(list(directory.glob("*.json"))) if directory.exists() else 0
    return {"service":"multi-exchange-trading-platform","mode":"live" if os.getenv("LIVE_TRADING")=="true" else "sandbox",
            "live_trading_enabled":os.getenv("LIVE_TRADING")=="true",
            "kill_switch_active":Path(os.getenv("KILL_SWITCH_FILE","/var/lib/trading/KILL")).exists(),
            "worker_ready":worker_state.ready(),"queue_counts":counts}

@app.post("/api/orders", status_code=202, dependencies=[Depends(require_token)])
def submit_approved_order(envelope: ApprovedOrderEnvelope) -> dict:
    """Queue a pre-signed risk approval. This API never creates or signs approvals."""
    proposal, approval = envelope.proposal, envelope.approval
    order_id = str(proposal.get("order_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", order_id):
        raise HTTPException(status_code=422, detail="INVALID_ORDER_ID")
    if str(approval.get("order_id", "")) != order_id:
        raise HTTPException(status_code=422, detail="ORDER_ID_MISMATCH")
    try:
        path = publish_order(str(SPOOL_DIR), f"{order_id}.json", envelope.model_dump(mode="json"))
    except FileExistsError:
        raise HTTPException(status_code=409, detail="ORDER_ALREADY_QUEUED") from None
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="ORDER_QUEUE_FAILED") from None
    return {"status":"queued","order_id":order_id,"queue_reference":path.name}

@app.get("/api/orders", dependencies=[Depends(require_token)])
def list_orders() -> dict:
    records = []
    for bucket in ("done", "rejected", "unknown"):
        directory = SPOOL_DIR / bucket
        if not directory.exists(): continue
        for path in sorted(directory.glob("*.result.json"), key=lambda p:p.stat().st_mtime, reverse=True)[:100]:
            try:
                item=json.loads(path.read_text()); response=item.get("exchange_response") or {}
                records.append({"bucket":bucket,"order_id":item.get("order_id"),"error":item.get("error"),
                    "exchange_order_id":response.get("id") or response.get("orderId"),"status":response.get("status"),
                    "symbol":response.get("symbol"),"filled":response.get("filled"),"average":response.get("average"),
                    "timestamp":response.get("timestamp")})
            except (OSError,json.JSONDecodeError): continue
    records.sort(key=lambda x:x.get("timestamp") or 0, reverse=True)
    return {"orders":records[:100]}

@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent.parent / "frontend" / "index.html")
