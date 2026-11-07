from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


Json = dict[str, Any]
Transport = Callable[[str, bytes, float], bytes]

_READ_METHODS = frozenset({
    "eth_chainId",
    "eth_blockNumber",
    "eth_getBalance",
    "eth_call",
    "eth_getCode",
    "eth_getTransactionReceipt",
})
_ARBITRUM_ONE_CHAIN_ID = 42161


class RpcError(RuntimeError):
    """Raised for transport, JSON-RPC, or chain-identity failures."""


def _https_transport(url: str, body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RpcError(f"JSON-RPC HTTP status {response.status}")
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RpcError("JSON-RPC transport failed") from exc


@dataclass(frozen=True)
class ArbitrumReadOnlyClient:
    """Minimal Arbitrum One JSON-RPC client restricted to read-only methods.

    It has no signer, private key, wallet, transaction-send, or deployment method.
    The endpoint must be HTTPS. Use a trusted provider URL from local environment.
    """

    rpc_url: str
    timeout_seconds: float = 10.0
    transport: Transport = _https_transport

    def __post_init__(self) -> None:
        if not self.rpc_url.startswith("https://"):
            raise ValueError("Arbitrum RPC endpoint must use HTTPS")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def request(self, method: str, params: list[Any] | None = None) -> Any:
        if method not in _READ_METHODS:
            raise ValueError(f"RPC method is not allowed in read-only mode: {method}")
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }).encode("utf-8")
        try:
            raw = self.transport(self.rpc_url, payload, self.timeout_seconds)
            decoded: Json = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise RpcError("Invalid JSON-RPC response") from exc
        if decoded.get("error"):
            # Do not include endpoint credentials or raw response in exceptions.
            error = decoded["error"]
            raise RpcError(f"JSON-RPC error code={error.get('code', 'unknown')}")
        if "result" not in decoded:
            raise RpcError("JSON-RPC response missing result")
        return decoded["result"]

    def chain_id(self) -> int:
        try:
            return int(self.request("eth_chainId"), 16)
        except (TypeError, ValueError) as exc:
            raise RpcError("Invalid chain ID response") from exc

    def require_arbitrum_one(self) -> int:
        chain_id = self.chain_id()
        if chain_id != _ARBITRUM_ONE_CHAIN_ID:
            raise RpcError(f"Unexpected chain ID {chain_id}; expected Arbitrum One (42161)")
        return chain_id

    def block_number(self) -> int:
        try:
            return int(self.request("eth_blockNumber"), 16)
        except (TypeError, ValueError) as exc:
            raise RpcError("Invalid block number response") from exc

    def get_balance_wei(self, address: str, block_tag: str = "latest") -> int:
        _validate_address(address)
        try:
            return int(self.request("eth_getBalance", [address, block_tag]), 16)
        except (TypeError, ValueError) as exc:
            raise RpcError("Invalid balance response") from exc

    def get_code(self, address: str, block_tag: str = "latest") -> str:
        _validate_address(address)
        result = self.request("eth_getCode", [address, block_tag])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RpcError("Invalid eth_getCode response")
        return result

    def eth_call(self, to: str, data: str, block_tag: str = "latest") -> str:
        _validate_address(to)
        if not isinstance(data, str) or not data.startswith("0x") or len(data) % 2:
            raise ValueError("call data must be 0x-prefixed even-length hex")
        result = self.request("eth_call", [{"to": to, "data": data}, block_tag])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RpcError("Invalid eth_call response")
        return result


def _validate_address(address: str) -> None:
    if (not isinstance(address, str) or len(address) != 42
            or not address.startswith("0x")
            or any(c not in "0123456789abcdefABCDEF" for c in address[2:])):
        raise ValueError("address must be a 20-byte 0x-prefixed hex string")
