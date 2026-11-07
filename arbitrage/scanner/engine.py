from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from arbitrage.risk.policy import ExecutionPolicy
from arbitrage.simulation.engine import SimulationConfig, SimulationEngine
from arbitrage.simulation.models import RouteQuote
from arbitrage.strategies.routes import validate_cross_dex_route

@dataclass(frozen=True)
class ScannerConfig:
    loan_premium_bps: int = 5
    gas_price_gwei: Decimal = Decimal("0.1")
    eth_price_usd: Decimal = Decimal("2000")
    usdc_price_usd: Decimal = Decimal("1")
    min_profit_usd: Decimal = Decimal("1")
    quote_block: int = 1_000_000

class OpportunityScanner:
    """Rule-based scanner over supplied quotes; built-in quote is synthetic."""
    def __init__(self, config: ScannerConfig | None = None) -> None:
        self.config = config or ScannerConfig()
        self.policy = ExecutionPolicy()
        self.simulator = SimulationEngine(SimulationConfig(
            loan_premium_bps=self.config.loan_premium_bps,
            gas_price_gwei=self.config.gas_price_gwei,
            native_token_price_usd=self.config.eth_price_usd,
            borrowed_asset_price_usd=self.config.usdc_price_usd,
            min_profit_usd=self.config.min_profit_usd,
            max_quote_age_blocks=3,
        ))

    def scan_synthetic_fixture(self, borrowed_amount: Decimal = Decimal("10000")) -> dict[str, Any]:
        self.policy.require_simulation()
        if not borrowed_amount.is_finite() or borrowed_amount <= 0:
            raise ValueError("borrowed_amount must be finite and positive")
        weth_out = borrowed_amount / Decimal("2000")
        final_usdc = borrowed_amount * Decimal("1.0025")
        route = (
            RouteQuote("Uniswap V3 (fixture)", "USDC", "WETH", borrowed_amount,
                       weth_out, 110_000, self.config.quote_block),
            RouteQuote("Camelot V3 (fixture)", "WETH", "USDC", weth_out,
                       final_usdc, 125_000, self.config.quote_block),
        )
        validate_cross_dex_route(route)
        result = self.simulator.simulate(
            strategy="cross_dex", borrowed_asset="USDC", borrowed_amount=borrowed_amount,
            route=route, current_block=self.config.quote_block,
        )
        record = result.to_record()
        record.update({
            "quote_source": "SYNTHETIC_FIXTURE",
            "market_data_verified": False,
            "executable": False,
            "risk_score": 0 if result.status.value == "REJECTED" else 25,
            "score_explanation": "Rule-based simulation score; not an AI prediction.",
        })
        return record
