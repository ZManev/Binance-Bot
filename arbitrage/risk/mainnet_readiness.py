from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from arbitrage.adapters.arbitrum import ArbitrumReadOnlyClient, RpcError
from arbitrage.integrations.aave_v3 import AaveV3ReadOnlyClient

ARBITRUM_ONE_CHAIN_ID = 42161
# Official protocol deployment references. Still checked for bytecode on the connected chain.
UNISWAP_V3_QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
CAMELOT_V3_AMMV3_QUOTER = "0x0Fc73040b26E9bC8514fA028D998E73A254Fa76E"
ARBITRUM_NATIVE_USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
ARBITRUM_WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"

@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

@dataclass(frozen=True)
class MainnetReadiness:
    environment: str
    chain_id: int
    capital_cap_usdc: str
    execution_profile: str
    execution_ready: bool
    signing_enabled: bool
    transaction_submission_enabled: bool
    deployment_enabled: bool
    checks: tuple[Check, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = [asdict(item) for item in self.checks]
        return data

def _configured_address(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default or "").strip()
    if len(value) != 42 or not value.startswith("0x") or any(c not in "0123456789abcdefABCDEF" for c in value[2:]):
        raise ValueError(f"{name} must be configured as a 20-byte hex address")
    return value

def inspect_mainnet_readiness(rpc: ArbitrumReadOnlyClient | None = None) -> MainnetReadiness:
    """Read-only preflight. It can never authorize or submit a transaction."""
    checks: list[Check] = []
    client = rpc
    if client is None:
        rpc_url = os.getenv("ARBITRUM_RPC_URL", "").strip()
        if not rpc_url:
            checks.append(Check("arbitrum_rpc", "NOT_CONFIGURED", "Set ARBITRUM_RPC_URL locally"))
        else:
            try:
                client = ArbitrumReadOnlyClient(rpc_url)
            except ValueError as exc:
                checks.append(Check("arbitrum_rpc", "FAIL", str(exc)))

    chain_id = 0
    chain_ok = False
    if client is not None:
        try:
            chain_id = client.require_arbitrum_one()
            block = client.block_number()
            chain_ok = True
            checks.append(Check("arbitrum_rpc", "PASS", f"Arbitrum One chainId=42161, block={block}"))
        except RpcError as exc:
            checks.append(Check("arbitrum_rpc", "FAIL", str(exc)))

    if client is not None and chain_ok:
        provider = os.getenv("AAVE_V3_ADDRESSES_PROVIDER", "").strip()
        if not provider:
            checks.append(Check("aave_v3", "NOT_CONFIGURED", "Set AAVE_V3_ADDRESSES_PROVIDER from the official Aave Address Book"))
        else:
            try:
                market = AaveV3ReadOnlyClient(client, provider).inspect_market()
                checks.append(Check("aave_v3", "PASS", f"Pool resolved and bytecode present: {market.pool}"))
            except (ValueError, RpcError) as exc:
                checks.append(Check("aave_v3", "FAIL", str(exc)))

        addresses = (
            ("uniswap_v3_quoter_v2", UNISWAP_V3_QUOTER_V2),
            ("camelot_v3_quoter", CAMELOT_V3_AMMV3_QUOTER),
            ("native_usdc", ARBITRUM_NATIVE_USDC),
            ("weth", ARBITRUM_WETH),
        )
        for name, address in addresses:
            try:
                code = client.get_code(address)
                if code in ("0x", "0x0"):
                    checks.append(Check(name, "FAIL", "No deployed bytecode at configured official reference"))
                else:
                    checks.append(Check(name, "PASS", "Contract bytecode present; ABI and live quote not yet verified"))
            except (ValueError, RpcError) as exc:
                checks.append(Check(name, "FAIL", str(exc)))
    else:
        reason = "Arbitrum One chain identity not verified" if client is not None else "No verified Arbitrum RPC connection"
        for name in ("aave_v3", "uniswap_v3_quoter_v2", "camelot_v3_quoter", "native_usdc", "weth"):
            if not any(c.name == name for c in checks):
                checks.append(Check(name, "NOT_RUN", reason))

    # This build intentionally has no signer or transaction-submission implementation.
    return MainnetReadiness(
        environment="MAINNET_READ_ONLY_PREPARATION",
        chain_id=chain_id,
        capital_cap_usdc="50",
        execution_profile="LIMITED_REQUESTED_BUT_NOT_IMPLEMENTED",
        execution_ready=False,
        signing_enabled=False,
        transaction_submission_enabled=False,
        deployment_enabled=False,
        checks=tuple(checks),
    )
