from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str = "SIMULATION"
    live_trading: bool = False
    allow_transaction_submission: bool = False
    allow_binance_spot_orders: bool = False

    def __post_init__(self) -> None:
        if self.mode != "SIMULATION":
            raise ValueError("this implementation supports SIMULATION mode only")
        if self.live_trading or self.allow_transaction_submission or self.allow_binance_spot_orders:
            raise ValueError("real execution flags must remain disabled in this implementation")

    def require_simulation(self) -> None:
        if self.mode != "SIMULATION" or self.live_trading or self.allow_transaction_submission or self.allow_binance_spot_orders:
            raise RuntimeError("EXECUTION_MODE_BLOCKED")
