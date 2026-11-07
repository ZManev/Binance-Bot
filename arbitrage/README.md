# Arbitrum AI Flash Loan Arbitrage — Simulation Foundation

This package is a simulation-only research foundation for cross-DEX and triangular arbitrage. The Arbitrum and Binance adapters added in this phase are **read-only**. No transaction submission, wallet signing, contract deployment, or Binance order path is implemented.

## Scope

- Decimal-based route and fee accounting.
- Configurable flash-loan premium and minimum net-profit threshold.
- Gas-cost estimate in USD using supplied gas units, gas price and native-token price.
- Quote block freshness and route-continuity checks.
- JSON-friendly opportunity records that explicitly state `transaction_submitted: false`.
- Fail-closed simulation-only execution policy.
- HTTPS-only Arbitrum JSON-RPC client with an allowlist of read methods and an Arbitrum One chain-ID check.
- Binance Spot GET-only market data and signed `GET /api/v3/account` read path.

## Run tests

From the repository root, with Python 3.12 and pytest installed:

```powershell
python -m pytest tests/test_arbitrage_*.py -q
```

The CI suite uses mocked transports and does not require network access, API credentials, wallets, RPC secrets, or exchange connectivity.

## Read-only adapter setup

Arbitrum:

- Supply an HTTPS Arbitrum One RPC endpoint to `ArbitrumReadOnlyClient`.
- Call `require_arbitrum_one()` before using chain data.
- The client allows only `eth_chainId`, `eth_blockNumber`, `eth_getBalance`, `eth_call`, `eth_getCode`, and `eth_getTransactionReceipt`.
- The client does not provide transaction-send or contract-deployment methods.

Binance Spot:

- Public GET endpoints need no credentials.
- For account reads, set `BINANCE_API_KEY` and `BINANCE_API_SECRET` in the local process environment; never commit or paste them into logs.
- Use an API key with **read-only permissions** and IP restrictions where available.
- The adapter fixes the host to `https://api.binance.com` and only allows ping, server time, ticker price, exchange info, and account GET paths.
- This is an account-data reader, not a trading adapter.

## Important assumptions

1. `RouteQuote.output_amount` is already net of DEX pool fees. Do not subtract the same fee twice.
2. The loan premium is a configurable model input, not a verified live Aave premium.
3. Gas cost is an estimate, not a measured transaction cost.
4. Read-only connectivity does not validate token addresses, pool addresses, route quality, or contract security.
5. A result with `SIMULATED` status is not proof of an executable or profitable on-chain opportunity.
6. No signing keys, exchange credentials or RPC write methods belong in this package.
7. The presence of a signed read-only Binance request does not authorize orders. `SIMULATION` remains the only supported mode.

## Not implemented yet

- Verified Arbitrum token/DEX address registry and quote decoding from audited ABIs.
- Aave V3 flash-loan receiver and Uniswap V3 swap contract.
- Foundry fork tests against a pinned Arbitrum block, including reverts, repayment, slippage, access control and invariant tests.
- Live RPC smoke evidence and separately reported Binance account-read evidence.
- Any execution enablement. Simulation remains the only supported execution mode.
