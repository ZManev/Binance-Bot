# AI Flash Loan Arbitrage Bot — Full Bot Foundation

**Environment: SIMULATION ONLY.** This is a research and simulation application, not an autonomous trading system.

## Included
- FastAPI backend and HTML dashboard.
- Deterministic cross-DEX opportunity scanner using the existing Decimal simulation engine.
- Profit model for Aave premium assumptions, estimated gas, and minimum net profit.
- Arbitrum One read-only RPC health check (chain ID 42161 and block number).
- Aave V3 read-only market inspection: resolve getPool() from a locally configured PoolAddressesProvider and verify deployed bytecode.
- Dashboard health, opportunity table, audit stream, and hard-lock indicators.
- Dedicated GitHub Actions workflow and API/scanner tests.

## Data provenance
The included scanner uses **synthetic fixture quotes** to exercise the complete route-validation and profitability pipeline. It does not discover real opportunities and must not be presented as live market data. Uniswap V3 and Camelot V3 are registry labels in the UI, not quote adapters. The Aave integration only performs read-only market discovery; it does not request or execute flash loans.

Official references:
- Arbitrum chain ID and RPC details: https://docs.arbitrum.io/chain-info
- Aave V3 PoolAddressesProvider: https://www.aave.com/docs/aave-v3/smart-contracts/pool-addresses-provider
- Aave V3 Pool: https://www.aave.com/docs/aave-v3/smart-contracts/pool
- Uniswap V3 Arbitrum deployments: https://developers.uniswap.org/docs/protocols/v3/deployments/v3-arbitrum-deployments
- Camelot Arbitrum deployments: https://docs.camelot.exchange/contracts/arbitrum/one-mainnet/

## Run locally
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-arbitrage.txt
uvicorn arbitrage.api.app:app --host 127.0.0.1 --port 8787

Open http://127.0.0.1:8787.

Optional read-only integration configuration: set ARBITRUM_RPC_URL and AAVE_V3_ADDRESSES_PROVIDER in the local environment. Never commit provider URLs containing credentials.

## Tests
python -m pytest tests/test_arbitrage_fullbot.py tests/test_arbitrage_*.py -q

## Hard safety boundary
- ExecutionPolicy remains SIMULATION-only.
- No private key, wallet signer, or signing library is added.
- No eth_sendTransaction, eth_sendRawTransaction, order endpoint, flash-loan execution, or deployment route is implemented.
- Dashboard controls only call health and simulation endpoints.
- Scanner output states transaction_submitted=false, transaction_hash=null, executable=false.
- Aave and Arbitrum integration endpoints use read-only RPC methods only.

A PASS on an offline test proves only that the tested code path passed. It is not proof of live liquidity, executable profit, deployed contract safety, or mainnet readiness.
