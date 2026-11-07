from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SimulationStatus(str, Enum):
    SIMULATED = "SIMULATED"
    REJECTED = "REJECTED"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class RouteQuote:
    """A deterministic swap quote; output_amount must already reflect pool fees.

    gas_units is an estimate, not a chain measurement. The quote is usable only
    for offline research unless its provenance is separately verified.
    """

    venue: str
    token_in: str
    token_out: str
    input_amount: Decimal
    output_amount: Decimal
    gas_units: int
    block_number: int | None = None

    def __post_init__(self) -> None:
        if not self.venue.strip():
            raise ValueError("venue is required")
        if not self.token_in.strip() or not self.token_out.strip():
            raise ValueError("token symbols are required")
        if self.token_in == self.token_out:
            raise ValueError("swap input and output token must differ")
        if not self.input_amount.is_finite() or self.input_amount <= 0:
            raise ValueError("input_amount must be finite and positive")
        if not self.output_amount.is_finite() or self.output_amount <= 0:
            raise ValueError("output_amount must be finite and positive")
        if self.gas_units < 0:
            raise ValueError("gas_units cannot be negative")
        if self.block_number is not None and self.block_number < 0:
            raise ValueError("block_number cannot be negative")


@dataclass(frozen=True)
class OpportunityResult:
    opportunity_id: str
    strategy: str
    status: SimulationStatus
    borrowed_asset: str
    borrowed_amount: Decimal
    output_amount: Decimal
    loan_premium: Decimal
    gas_cost_usd: Decimal
    borrowed_asset_price_usd: Decimal
    gross_profit_usd: Decimal
    net_profit_usd: Decimal
    min_profit_usd: Decimal
    route: tuple[RouteQuote, ...]
    reason: str
    environment: str = "SIMULATION"

    def to_record(self) -> dict[str, object]:
        """Return JSON-friendly audit data; no execution claims are implied."""
        return {
            "schema_version": "1.0",
            "opportunity_id": self.opportunity_id,
            "strategy": self.strategy,
            "environment": self.environment,
            "status": self.status.value,
            "borrowed_asset": self.borrowed_asset,
            "borrowed_amount": str(self.borrowed_amount),
            "output_amount": str(self.output_amount),
            "loan_premium": str(self.loan_premium),
            "gas_cost_usd": str(self.gas_cost_usd),
            "borrowed_asset_price_usd": str(self.borrowed_asset_price_usd),
            "gross_profit_usd": str(self.gross_profit_usd),
            "net_profit_usd": str(self.net_profit_usd),
            "min_profit_usd": str(self.min_profit_usd),
            "reason": self.reason,
            "transaction_submitted": False,
            "transaction_hash": None,
            "route": [
                {
                    "venue": q.venue,
                    "token_in": q.token_in,
                    "token_out": q.token_out,
                    "input_amount": str(q.input_amount),
                    "output_amount": str(q.output_amount),
                    "gas_units": q.gas_units,
                    "block_number": q.block_number,
                }
                for q in self.route
            ],
        }
