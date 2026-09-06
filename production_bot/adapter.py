from __future__ import annotations

from typing import Any

import ccxt

from .models import AuthorizedOrder
from .secrets import BinanceCredentialProvider


class BinanceAdapter:
    """Exchange transport only. It accepts AuthorizedOrder, never TradeProposal."""

    def __init__(self, credentials: BinanceCredentialProvider, testnet: bool = True) -> None:
        creds = credentials.get()
        self.exchange = ccxt.binance({
            "apiKey": creds.api_key,
            "secret": creds.api_secret,
            "enableRateLimit": True,
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)

    def submit(self, order: AuthorizedOrder) -> dict[str, Any]:
        p = order.proposal
        if p.order_type == "market":
            return self.exchange.create_order(
                p.symbol, "market", p.side, float(p.quantity)
            )
        if p.price is None:
            raise ValueError("LIMIT_ORDER_REQUIRES_PRICE")
        return self.exchange.create_order(
            p.symbol, "limit", p.side, float(p.quantity), float(p.price)
        )
