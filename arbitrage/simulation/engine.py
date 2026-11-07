from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from .models import OpportunityResult, RouteQuote, SimulationStatus


@dataclass(frozen=True)
class SimulationConfig:
    loan_premium_bps: int
    gas_price_gwei: Decimal
    native_token_price_usd: Decimal
    borrowed_asset_price_usd: Decimal
    min_profit_usd: Decimal
    max_slippage_bps: int = 100
    max_quote_age_blocks: int = 3

    def __post_init__(self) -> None:
        if not 0 <= self.loan_premium_bps <= 10_000:
            raise ValueError("loan_premium_bps must be between 0 and 10000")
        if not self.gas_price_gwei.is_finite() or self.gas_price_gwei < 0:
            raise ValueError("gas_price_gwei must be finite and non-negative")
        for name, value in (("native_token_price_usd", self.native_token_price_usd),
                            ("borrowed_asset_price_usd", self.borrowed_asset_price_usd),
                            ("min_profit_usd", self.min_profit_usd)):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0 <= self.max_slippage_bps <= 10_000:
            raise ValueError("max_slippage_bps must be between 0 and 10000")
        if self.max_quote_age_blocks < 0:
            raise ValueError("max_quote_age_blocks cannot be negative")


class SimulationEngine:
    """Offline simulator. It has no RPC client, signer, or exchange adapter."""

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def simulate(self, *, strategy: str, borrowed_asset: str, borrowed_amount: Decimal,
                 route: tuple[RouteQuote, ...], current_block: int | None = None,
                 opportunity_id: str | None = None) -> OpportunityResult:
        if not strategy.strip() or not borrowed_asset.strip():
            raise ValueError("strategy and borrowed_asset are required")
        if not borrowed_amount.is_finite() or borrowed_amount <= 0:
            raise ValueError("borrowed_amount must be finite and positive")
        if not route:
            raise ValueError("route must contain at least one swap")

        reason = self._validate_route(borrowed_asset, borrowed_amount, route, current_block)
        output_amount = route[-1].output_amount
        premium = borrowed_amount * Decimal(self.config.loan_premium_bps) / Decimal(10_000)
        gas_units = sum(q.gas_units for q in route)
        # 1 gwei = 1e-9 native tokens. This is a model, not a measured gas charge.
        gas_cost_usd = (Decimal(gas_units) * self.config.gas_price_gwei * Decimal("1e-9")
                        * self.config.native_token_price_usd)
        gross_profit_usd = (output_amount - borrowed_amount - premium) * self.config.borrowed_asset_price_usd
        net_profit_usd = gross_profit_usd - gas_cost_usd
        status = SimulationStatus.SIMULATED
        if reason:
            status = SimulationStatus.REJECTED
        elif net_profit_usd < self.config.min_profit_usd:
            status = SimulationStatus.REJECTED
            reason = "NET_PROFIT_BELOW_MINIMUM"
        else:
            reason = "SIMULATION_PROFIT_THRESHOLD_MET_NOT_EXECUTABLE_PROOF"

        return OpportunityResult(
            opportunity_id=opportunity_id or uuid4().hex,
            strategy=strategy,
            status=status,
            borrowed_asset=borrowed_asset,
            borrowed_amount=borrowed_amount,
            output_amount=output_amount,
            loan_premium=premium,
            gas_cost_usd=gas_cost_usd,
            borrowed_asset_price_usd=self.config.borrowed_asset_price_usd,
            gross_profit_usd=gross_profit_usd,
            net_profit_usd=net_profit_usd,
            min_profit_usd=self.config.min_profit_usd,
            route=route,
            reason=reason,
        )

    def _validate_route(self, borrowed_asset: str, borrowed_amount: Decimal,
                        route: tuple[RouteQuote, ...], current_block: int | None) -> str:
        if route[0].token_in != borrowed_asset:
            return "ROUTE_DOES_NOT_START_WITH_BORROWED_ASSET"
        if route[0].input_amount != borrowed_amount:
            return "FIRST_SWAP_INPUT_MISMATCH"
        for previous, current in zip(route, route[1:]):
            if previous.token_out != current.token_in:
                return "DISCONNECTED_ROUTE"
            if previous.output_amount != current.input_amount:
                return "INTERMEDIATE_AMOUNT_MISMATCH"
        if route[-1].token_out != borrowed_asset:
            return "ROUTE_DOES_NOT_REPAY_BORROWED_ASSET"
        if current_block is not None:
            for quote in route:
                if quote.block_number is None:
                    return "QUOTE_BLOCK_UNVERIFIED"
                if quote.block_number > current_block:
                    return "QUOTE_FROM_FUTURE_BLOCK"
                if current_block - quote.block_number > self.config.max_quote_age_blocks:
                    return "STALE_QUOTE"
        return ""
