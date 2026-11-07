from decimal import Decimal as D

import pytest

from arbitrage.risk.policy import ExecutionPolicy
from arbitrage.simulation.engine import SimulationConfig, SimulationEngine
from arbitrage.simulation.models import RouteQuote, SimulationStatus
from arbitrage.strategies.routes import validate_cross_dex_route, validate_triangular_route
from arbitrage.strategies.types import RouteShapeError


@pytest.fixture
def engine():
    return SimulationEngine(SimulationConfig(
        loan_premium_bps=5,
        gas_price_gwei=D("0.1"),
        native_token_price_usd=D("2"),
        borrowed_asset_price_usd=D("1"),
        min_profit_usd=D("1"),
        max_quote_age_blocks=3,
    ))


def q(venue, token_in, token_out, amount_in, amount_out, gas=100_000, block=100):
    return RouteQuote(venue, token_in, token_out, D(amount_in), D(amount_out), gas, block)


def test_profitable_cross_dex_simulation_is_not_execution(engine):
    route = (q("dex-a", "USDC", "WETH", "10000", "5"),
             q("dex-b", "WETH", "USDC", "5", "10020"))
    validate_cross_dex_route(route)
    result = engine.simulate(strategy="cross_dex", borrowed_asset="USDC",
                             borrowed_amount=D("10000"), route=route, current_block=101,
                             opportunity_id="fixture-cross-001")
    assert result.status is SimulationStatus.SIMULATED
    assert result.net_profit_usd > D("1")
    record = result.to_record()
    assert record["transaction_submitted"] is False
    assert record["transaction_hash"] is None
    assert record["environment"] == "SIMULATION"


def test_unprofitable_route_is_rejected(engine):
    route = (q("dex-a", "USDC", "WETH", "10000", "5"),
             q("dex-b", "WETH", "USDC", "5", "9990"))
    # Route is connected, but proceeds cannot repay principal, premium and gas.
    result = engine.simulate(strategy="cross_dex", borrowed_asset="USDC",
                             borrowed_amount=D("10000"), route=route, current_block=101)
    assert result.status is SimulationStatus.REJECTED
    assert result.reason == "NET_PROFIT_BELOW_MINIMUM"


def test_triangular_cycle_validation():
    route = (q("dex-a", "USDC", "WETH", "10000", "5"),
             q("dex-b", "WETH", "ARB", "5", "2000"),
             q("dex-c", "ARB", "USDC", "2000", "10050"))
    validate_triangular_route(route)


def test_triangular_rejects_wrong_number_of_legs():
    route = (q("dex-a", "USDC", "WETH", "10000", "5"),
             q("dex-b", "WETH", "USDC", "5", "10050"))
    with pytest.raises(RouteShapeError):
        validate_triangular_route(route)


def test_stale_quotes_are_rejected(engine):
    route = (q("dex-a", "USDC", "WETH", "10000", "5", block=90),
             q("dex-b", "WETH", "USDC", "5", "10050", block=90))
    result = engine.simulate(strategy="cross_dex", borrowed_asset="USDC",
                             borrowed_amount=D("10000"), route=route, current_block=101)
    assert result.status is SimulationStatus.REJECTED
    assert result.reason == "STALE_QUOTE"


def test_route_must_return_borrowed_asset(engine):
    route = (q("dex-a", "USDC", "WETH", "10000", "5"),)
    result = engine.simulate(strategy="cross_dex", borrowed_asset="USDC",
                             borrowed_amount=D("10000"), route=route)
    assert result.status is SimulationStatus.REJECTED
    assert result.reason == "ROUTE_DOES_NOT_REPAY_BORROWED_ASSET"


def test_simulation_policy_fails_closed():
    ExecutionPolicy().require_simulation()
    with pytest.raises(ValueError):
        ExecutionPolicy(live_trading=True)
    with pytest.raises(ValueError):
        ExecutionPolicy(allow_transaction_submission=True)
    with pytest.raises(ValueError):
        ExecutionPolicy(allow_binance_spot_orders=True)


def test_route_amount_mismatch_is_rejected(engine):
    route = (q("dex-a", "USDC", "WETH", "10000", "5"),
             q("dex-b", "WETH", "USDC", "4.9", "10050"))
    result = engine.simulate(strategy="cross_dex", borrowed_asset="USDC",
                             borrowed_amount=D("10000"), route=route)
    assert result.status is SimulationStatus.REJECTED
    assert result.reason == "INTERMEDIATE_AMOUNT_MISMATCH"
