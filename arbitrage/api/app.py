from __future__ import annotations
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from arbitrage.adapters.arbitrum import ArbitrumReadOnlyClient, RpcError
from arbitrage.integrations.aave_v3 import AaveV3ReadOnlyClient
from arbitrage.scanner.engine import OpportunityScanner

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard" / "index.html"
app = FastAPI(title="AI Flash Loan Arbitrage Bot", version="0.1.0",
              description="Arbitrum/Aave V3 research terminal. SIMULATION ONLY.")
scanner = OpportunityScanner()

class ScanRequest(BaseModel):
    borrowed_amount: Decimal = Field(default=Decimal("10000"), gt=0, max_digits=28, decimal_places=8)

@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD)

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status":"ok","mode":"SIMULATION","chain_target":"Arbitrum One","chain_id":42161,
            "signing_enabled":False,"transaction_submission_enabled":False,"deployment_enabled":False}

@app.get("/api/status")
def status() -> dict[str, Any]:
    return {"mode":"SIMULATION","risk_engine":"ACTIVE","execution_gate":"LOCKED",
            "market_data":"SYNTHETIC_FIXTURE",
            "arbitrum_rpc":"CONFIGURED" if os.getenv("ARBITRUM_RPC_URL") else "NOT_CONFIGURED",
            "aave_v3":"CONFIGURED" if os.getenv("AAVE_V3_ADDRESSES_PROVIDER") else "NOT_CONFIGURED",
            "signing":"DISABLED","submission":"DISABLED"}

@app.get("/api/integrations/arbitrum")
def arbitrum_status() -> dict[str, Any]:
    rpc_url = os.getenv("ARBITRUM_RPC_URL", "").strip()
    if not rpc_url:
        return {"status":"NOT_CONFIGURED","chain_id":None,"block_number":None}
    try:
        client = ArbitrumReadOnlyClient(rpc_url)
        return {"status":"PASS","chain_id":client.require_arbitrum_one(),
                "block_number":client.block_number(),"read_only":True}
    except (ValueError, RpcError) as exc:
        return {"status":"FAIL","reason":str(exc),"read_only":True}

@app.get("/api/integrations/aave")
def aave_status() -> dict[str, Any]:
    try:
        market = AaveV3ReadOnlyClient.from_environment().inspect_market()
        return {"status":"PASS","chain_id":market.chain_id,
                "addresses_provider":market.addresses_provider,"pool":market.pool,
                "pool_has_code":market.pool_has_code,"read_only":True}
    except (ValueError, RpcError) as exc:
        return {"status":"NOT_VERIFIED","reason":str(exc),"read_only":True}

@app.get("/api/opportunities")
def opportunities() -> dict[str, Any]:
    return {"items":[scanner.scan_synthetic_fixture()],"source":"SYNTHETIC_FIXTURE"}

@app.post("/api/scan")
def scan(request: ScanRequest) -> dict[str, Any]:
    try:
        return scanner.scan_synthetic_fixture(request.borrowed_amount)
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
