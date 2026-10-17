from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from datetime import datetime, timezone

import ccxt

from .gate import PreSubmitRejection
from .models import AuthorizedOrder
from .security import order_hash, verify_approval


class UnauthorizedOrder(PreSubmitRejection):
    pass


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

    def __init__(self, exchange_id: str, credentials: ExchangeCredentialProvider, signing_secret: bytes, sandbox: bool = False) -> None:
        if exchange_id not in self.SUPPORTED:
            raise ValueError(f"UNSUPPORTED_EXCHANGE:{exchange_id}")
        if not signing_secret:
            raise ValueError("SIGNING_SECRET_REQUIRED")
        self._signing_secret = signing_secret
        creds = credentials.get(exchange_id)
        exchange_cls = getattr(ccxt, exchange_id)
        config: dict[str, Any] = {"apiKey": creds.api_key, "secret": creds.api_secret, "enableRateLimit": True}
        if creds.password:
            config["password"] = creds.password
        self.exchange_id = exchange_id
        self.exchange = exchange_cls(config)
        if sandbox:
            self.exchange.set_sandbox_mode(True)

    def _verify(self, order: AuthorizedOrder) -> None:
        p = order.proposal
        a = order.approval
        digest = order_hash(p)
        if a.order_id != p.order_id:
            raise UnauthorizedOrder("ORDER_ID_MISMATCH")
        if a.order_hash != digest:
            raise UnauthorizedOrder("ORDER_HASH_MISMATCH")
        if datetime.now(timezone.utc) >= a.expires_at:
            raise UnauthorizedOrder("APPROVAL_EXPIRED")
        if a.approved_quantity != p.quantity:
            raise UnauthorizedOrder("APPROVED_QUANTITY_MISMATCH")
        if not verify_approval(digest, a.policy_version, a.nonce, a.expires_at.isoformat(), a.signature, self._signing_secret):
            raise UnauthorizedOrder("INVALID_APPROVAL_SIGNATURE")

    def submit(self, order: AuthorizedOrder) -> dict[str, Any]:
        self._verify(order)
        p = order.proposal
        if p.order_type == "market":
            return self.exchange.create_order(p.symbol, "market", p.side, float(p.quantity))
        if p.price is None:
            raise ValueError("LIMIT_ORDER_REQUIRES_PRICE")
        return self.exchange.create_order(p.symbol, "limit", p.side, float(p.quantity), float(p.price))

    def fetch_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        return self.exchange.fetch_order(exchange_order_id, symbol)
