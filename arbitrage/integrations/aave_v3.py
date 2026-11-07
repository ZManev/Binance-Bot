from __future__ import annotations
import os
from dataclasses import dataclass
from arbitrage.adapters.arbitrum import ArbitrumReadOnlyClient, RpcError

_GET_POOL_SELECTOR = "0x026b1d5f"

def _address(value: str) -> str:
    if (not isinstance(value, str) or len(value) != 42 or not value.startswith("0x")
            or any(c not in "0123456789abcdefABCDEF" for c in value[2:])):
        raise ValueError("Aave address must be a 20-byte 0x-prefixed hex string")
    return value

@dataclass(frozen=True)
class AaveV3Market:
    chain_id: int
    addresses_provider: str
    pool: str
    pool_has_code: bool

@dataclass(frozen=True)
class AaveV3ReadOnlyClient:
    """Resolve Aave V3 market addresses using eth_call only."""
    rpc: ArbitrumReadOnlyClient
    addresses_provider: str

    def __post_init__(self) -> None:
        _address(self.addresses_provider)

    @classmethod
    def from_environment(cls) -> "AaveV3ReadOnlyClient":
        rpc_url = os.getenv("ARBITRUM_RPC_URL", "").strip()
        provider = os.getenv("AAVE_V3_ADDRESSES_PROVIDER", "").strip()
        if not rpc_url or not provider:
            raise ValueError("ARBITRUM_RPC_URL and AAVE_V3_ADDRESSES_PROVIDER are required")
        return cls(ArbitrumReadOnlyClient(rpc_url), provider)

    def inspect_market(self) -> AaveV3Market:
        chain_id = self.rpc.require_arbitrum_one()
        raw_pool = self.rpc.eth_call(self.addresses_provider, _GET_POOL_SELECTOR)
        if not isinstance(raw_pool, str) or len(raw_pool) < 66:
            raise RpcError("Aave getPool() returned malformed data")
        pool = _address("0x" + raw_pool[-40:])
        if int(pool[2:], 16) == 0:
            raise RpcError("Aave Pool address resolved to zero")
        code = self.rpc.get_code(pool)
        if code in ("0x", "0x0"):
            raise RpcError("Aave Pool address has no deployed bytecode")
        return AaveV3Market(chain_id, self.addresses_provider, pool, True)
