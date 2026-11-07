from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable


BINANCE_SPOT_BASE_URL = "https://api.binance.com"
Json = dict[str, Any]
GetTransport = Callable[[str, dict[str, str], float], bytes]


class BinanceReadOnlyError(RuntimeError):
    """Raised when a read-only Binance Spot request fails."""


def _https_get(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise BinanceReadOnlyError(f"Binance HTTP status {response.status}")
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BinanceReadOnlyError("Binance HTTPS request failed") from exc


@dataclass(frozen=True)
class BinanceSpotReadOnlyClient:
    """Binance Spot market-data and signed account-read adapter.

    Only GET endpoints are implemented. There are deliberately no order, cancel,
    withdrawal, or account-mutation methods. API credentials are read from the
    process environment and are never returned or logged.
    """

    api_key: str | None = None
    api_secret: str | None = None
    timeout_seconds: float = 10.0
    transport: GetTransport = _https_get

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.api_key is not None and not self.api_key.strip():
            raise ValueError("api_key cannot be blank")
        if self.api_secret is not None and not self.api_secret.strip():
            raise ValueError("api_secret cannot be blank")

    @classmethod
    def from_environment(cls) -> "BinanceSpotReadOnlyClient":
        return cls(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET"),
        )

    def _get_json(self, path: str, params: dict[str, str] | None = None,
                  *, signed: bool = False) -> Any:
        # Keep paths internal to this module; do not accept caller-provided URLs.
        allowed_paths = {"/api/v3/ping", "/api/v3/time", "/api/v3/ticker/price",
                         "/api/v3/exchangeInfo", "/api/v3/account"}
        if path not in allowed_paths:
            raise ValueError("Endpoint is not allowlisted for read-only access")
        query = dict(params or {})
        headers = {"Accept": "application/json"}
        if signed:
            if not self.api_key or not self.api_secret:
                raise BinanceReadOnlyError("Signed account read requires local API credentials")
            query.setdefault("recvWindow", "5000")
            query.setdefault("timestamp", str(self._server_timestamp_ms()))
            query_string = urllib.parse.urlencode(query)
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            query_string += "&signature=" + signature
            headers["X-MBX-APIKEY"] = self.api_key
        else:
            query_string = urllib.parse.urlencode(query)
        url = BINANCE_SPOT_BASE_URL + path
        if query_string:
            url += "?" + query_string
        try:
            raw = self.transport(url, headers, self.timeout_seconds)
            return json.loads(raw.decode("utf-8"))
        except BinanceReadOnlyError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise BinanceReadOnlyError("Invalid Binance JSON response") from exc

    def ping(self) -> bool:
        result = self._get_json("/api/v3/ping")
        if result != {}:
            raise BinanceReadOnlyError("Unexpected ping response")
        return True

    def server_time_ms(self) -> int:
        result = self._get_json("/api/v3/time")
        try:
            value = int(result["serverTime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceReadOnlyError("Invalid Binance server-time response") from exc
        if value <= 0:
            raise BinanceReadOnlyError("Invalid Binance server-time value")
        return value

    def _server_timestamp_ms(self) -> int:
        # Use exchange time for signed requests; never send a trade or mutation.
        return self.server_time_ms()

    def ticker_price(self, symbol: str) -> Decimal:
        symbol = _validate_symbol(symbol)
        result = self._get_json("/api/v3/ticker/price", {"symbol": symbol})
        try:
            price = Decimal(result["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceReadOnlyError("Invalid ticker-price response") from exc
        if not price.is_finite() or price <= 0:
            raise BinanceReadOnlyError("Ticker price must be finite and positive")
        return price

    def exchange_info(self, symbol: str | None = None) -> Json:
        params = {"symbol": _validate_symbol(symbol)} if symbol else {}
        result = self._get_json("/api/v3/exchangeInfo", params)
        if not isinstance(result, dict):
            raise BinanceReadOnlyError("Invalid exchange-info response")
        return result

    def account_read_only(self) -> Json:
        """Fetch authenticated account data. Configure a key with read-only permissions."""
        result = self._get_json("/api/v3/account", signed=True)
        if not isinstance(result, dict) or not isinstance(result.get("balances"), list):
            raise BinanceReadOnlyError("Invalid account response")
        return result


def _validate_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized or len(normalized) > 30 or not normalized.isalnum():
        raise ValueError("symbol must contain only letters and digits")
    return normalized
