from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import ccxt

from .models import AuthorizedOrder


@dataclass(frozen=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str
    password: str | None = None


class ExchangeCredentialProvider(Protocol):
    def get(self, exchange_id: str) -> ExchangeCredentials: ...


class MultiExchangeAdapter(Protocol):
    exchange_id: str
    def submit(self, order: AuthorizedOrder) -> dict[str, Any]: ...
    def fetch_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]: ...


class CcxtExchangeAdapter:
    """Controlled CCXT transport. It never accepts an unapproved TradeProposal."""

    SUPPORTED = frozenset({"binance", "kraken", "coinbase"})

    def __init__(self, exchange_id: str, credentials: ExchangeCredentialProvider, sandbox: bool = False) -> None:
        if exchange_id not in self.SUPPORTED:
            raise ValueError(f"UNSUPPORTED_EXCHANGE:{exchange_id}")
        creds = credentials.get(exchange_id)
        exchange_cls = getattr(ccxt, exchange_id)
        config: dict[str, Any] = {"apiKey": creds.api_key, "secret": creds.api_secret, "enableRateLimit": True}
        if creds.password:
            config["password"] = creds.password
        self.exchange_id = exchange_id
        self.exchange = exchange_cls(config)
        if sandbox:
            self.exchange.set_sandbox_mode(True)

    def submit(self, order: AuthorizedOrder) -> dict[str, Any]:
        p = order.proposal
        if p.order_type == "market":
            return self.exchange.create_order(p.symbol, "market", p.side, float(p.quantity))
        if p.price is None:
            raise ValueError("LIMIT_ORDER_REQUIRES_PRICE")
        return self.exchange.create_order(p.symbol, "limit", p.side, float(p.quantity), float(p.price))

    def fetch_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        return self.exchange.fetch_order(exchange_order_id, symbol)
