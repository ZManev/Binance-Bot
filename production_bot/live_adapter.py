from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter import BinanceAdapter
from .fills import FillEvent, fill_from_ccxt_trade
from .models import AuthorizedOrder


class LiveExecutionBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveExecutionConfig:
    symbol_allowlist: frozenset[str] = frozenset({"BTC/USDT", "BTCUSDT"})
    testnet: bool = True
    live_trading_enabled: bool = False

    def validate(self) -> None:
        if not self.symbol_allowlist:
            raise ValueError("SYMBOL_ALLOWLIST_REQUIRED")


class ProductionBinanceAdapter:
    """Production execution boundary around the existing BinanceAdapter."""

    def __init__(self, adapter: BinanceAdapter, config: LiveExecutionConfig) -> None:
        config.validate()
        self.adapter = adapter
        self.config = config

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        value = symbol.strip().upper()
        return "BTC/USDT" if value == "BTCUSDT" else value

    def _check(self, order: AuthorizedOrder) -> None:
        symbol = self.normalize_symbol(order.proposal.symbol)
        allowed = {self.normalize_symbol(s) for s in self.config.symbol_allowlist}
        if symbol not in allowed:
            raise LiveExecutionBlocked("SYMBOL_NOT_ALLOWED")
        if not self.config.testnet and not self.config.live_trading_enabled:
            raise LiveExecutionBlocked("LIVE_TRADING_DISABLED")

    def submit(self, order: AuthorizedOrder) -> tuple[dict[str, Any], list[FillEvent]]:
        self._check(order)
        result = self.adapter.submit(order)
        fills: list[FillEvent] = []
        for trade in result.get("trades") or []:
            fill = fill_from_ccxt_trade(result, trade)
            if fill.quantity > 0 and fill.price > 0:
                fills.append(fill)
        return result, fills
