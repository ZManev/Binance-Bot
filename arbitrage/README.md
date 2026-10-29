# Arbitrum AI Flash Loan Arbitrage — Simulation Foundation

This package is a deterministic, offline research foundation for cross-DEX and triangular arbitrage. It deliberately has no RPC client, wallet signer, contract deployment, Binance order adapter, or transaction submission path.

## Scope

- Decimal-based route and fee accounting.
- Configurable flash-loan premium and minimum net-profit threshold.
- Gas-cost estimate in USD using supplied gas units, gas price and native-token price.
- Quote block freshness and route-continuity checks.
- JSON-friendly opportunity records that explicitly state `transaction_submitted: false`.
- Fail-closed simulation-only execution policy.

## Run tests

From the repository root, with pytest installed:

```powershell
python -m pytest tests/arbitrage -q
```

## Important assumptions

1. `RouteQuote.output_amount` is already net of DEX pool fees. Do not subtract the same fee twice.
2. The loan premium is a configurable model input, not a verified live Aave premium.
3. Gas cost is an estimate, not a measured transaction cost.
4. Quote data must come from a separately implemented and verified data adapter before being used for research conclusions.
5. A result with `SIMULATED` status is not proof of an executable or profitable on-chain opportunity.
6. No signing keys, exchange credentials or RPC write methods belong in this package.

## Not implemented yet

- Live Arbitrum RPC quote collection and trusted address registry.
- Aave V3 contract integration and Solidity receiver.
- Uniswap V3 swap adapter and fork tests.
- Binance Spot market-data and authenticated read-only adapter.
- CI wiring and proof artifacts for the new test suite.
