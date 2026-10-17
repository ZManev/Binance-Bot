"""Minimal authenticated dashboard API; never creates risk approvals or grants authority.

The API accepts only pre-approved order envelopes, writes them atomically to the
execution spool, and exposes sanitized execution records. Keep it behind a private
network/reverse proxy. The execution gate remains the only order authority.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .order_spool import publish_order

SPOOL_DIR = Path(os.getenv("SPOOL_DIR", "/var/lib/trading/spool"))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_API_TOKEN", "")
app = FastAPI(title="Trading Execution Dashboard API", version="1.0.0", docs_url=None, redoc_url=None)

def require_token(authorization: str | None = Header(default=None)) -> None:
    if not DASHBOARD_TOKEN:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_TOKEN_NOT_CONFIGURED")
    expected = f"Bearer {DASHBOARD_TOKEN}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")

class ApprovedOrderEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal: dict[str, Any]
    approval: dict[str, Any]

@app.get("/api/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "dashboard-api"}

@app.get("/api/status", dependencies=[Depends(require_token)])
def status() -> dict:
    counts: dict[str, int] = {}
    for bucket in ("incoming", "processing", "done", "rejected", "unknown"):
        directory = SPOOL_DIR / bucket
        counts[bucket] = len(list(directory.glob("*.json"))) if directory.exists() else 0
    return {
        "service": "multi-exchange-trading-platform",
        "mode": "live" if os.getenv("LIVE_TRADING") == "true" else "sandbox",
        "live_trading_enabled": os.getenv("LIVE_TRADING") == "true",
        "kill_switch_active": Path(os.getenv("KILL_SWITCH_FILE", "/var/lib/trading/KILL")).exists(),
        "queue_counts": counts,
    }

@app.post("/api/orders", status_code=202, dependencies=[Depends(require_token)])
def submit_approved_order(envelope: ApprovedOrderEnvelope) -> dict:
    """Queue a signed risk-approved order; does not calculate or sign approvals."""
    proposal = envelope.proposal
    approval = envelope.approval
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
    return {"status": "queued", "order_id": order_id, "queue_reference": path.name}

@app.get("/api/orders", dependencies=[Depends(require_token)])
def list_orders() -> dict:
    """Return result metadata only; never return secrets or full exchange payloads."""
    records = []
    for bucket in ("done", "rejected", "unknown"):
        directory = SPOOL_DIR / bucket
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.result.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                item = json.loads(path.read_text())
                response = item.get("exchange_response") or {}
                records.append({
                    "bucket": bucket,
                    "order_id": item.get("order_id"),
                    "error": item.get("error"),
                    "exchange_order_id": response.get("id") or response.get("orderId"),
                    "status": response.get("status"),
                    "symbol": response.get("symbol"),
                    "filled": response.get("filled"),
                    "average": response.get("average"),
                    "timestamp": response.get("timestamp"),
                })
            except (OSError, json.JSONDecodeError):
                continue
    records.sort(key=lambda x: x.get("timestamp") or 0, reverse=True)
    return {"orders": records[:100]}

@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent.parent / "frontend" / "index.html")
