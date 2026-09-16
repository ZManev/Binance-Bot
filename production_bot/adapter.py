from __future__ import annotations

from typing import Any

import ccxt

from .models import AuthorizedOrder
from .secrets import BinanceCredentialProvider


class LiveExecutionBlocked(RuntimeError):
    pass


class BinanceAdapter:
    """Exchange transport only.

    This class accepts AuthorizedOrder, never TradeProposal. Sandbox/Testnet is
    the default. Real-money execution requires an explicit deployment flag.
    """

    def __init__(
        self,
        credentials: BinanceCredentialProvider,
        testnet: bool = True,
        live_trading_enabled: bool = False,
    ) -> None:
        if not testnet and not live_trading_enabled:
            raise LiveExecutionBlocked("LIVE_TRADING_DISABLED")

        creds = credentials.get()
        self.exchange = ccxt.binance({
            "apiKey": creds.api_key,
            "secret": creds.api_secret,
            "enableRateLimit": True,
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        value = symbol.strip().upper()
        return "BTC/USDT" if value == "BTCUSDT" else value

    def submit(self, order: AuthorizedOrder) -> dict[str, Any]:
        p = order.proposal
        symbol = self.normalize_symbol(p.symbol)
        if p.order_type == "market":
            return self.exchange.create_order(
                symbol, "market", p.side, float(p.quantity)
            )
        if p.price is None:
            raise ValueError("LIMIT_ORDER_REQUIRES_PRICE")
        return self.exchange.create_order(
            symbol, "limit", p.side, float(p.quantity), float(p.price)
        )
