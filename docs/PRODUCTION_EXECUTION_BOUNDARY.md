# Production Execution Boundary — Binance Spot

## Release posture

**This branch is a security-foundation change, not a live-trading release.**
The only permitted mode in this implementation is **SIMULATION_ONLY**:

- LIVE_TRADING=false
- SIGNING_ENABLED=false
- ORDER_SUBMISSION_ENABLED=false

Any attempt to set one of these values to true causes configuration to fail closed. No function in this boundary module calls an exchange order endpoint.

## Trust boundaries

1. Strategy service emits an immutable TradeProposal; it has no exchange credentials.
2. Risk Authority evaluates limits and issues a short-lived, order-bound approval. Its Ed25519 private key is held outside the execution service (HSM/KMS custody); it is never mounted in the strategy or adapter process.
3. Execution service has only the Risk Authority public key. It verifies canonical claims, environment, expiry, maximum TTL, and signature.
4. Durable storage atomically reserves both order ID and approval nonce. A duplicate or replay is rejected.
5. Kill switch is checked immediately before authorization. Missing/unreadable kill-switch state is treated as halted.
6. The adapter is a separate trust boundary. It must independently validate an unforgeable permit, account/venue/symbol allowlists, exchange filters, approved notional, kill switch, and durable reservation before any network call. It must not accept TradeProposal or raw AuthorizedOrder.
7. A timeout after a possible network send transitions to UNKNOWN. UNKNOWN is never retried automatically; reconciliation must query the exchange by client order ID and resolve the state.
8. Every decision is written to a persistent, hash-chained audit ledger. Production deployment must additionally export the ledger to append-only/WORM storage and alert on verification failure.

## Required state machine

RESERVED → SUBMITTING → ACKNOWLEDGED → RECONCILED

Pre-submit rejection may transition RESERVED → REJECTED. Any ambiguous post-send outcome transitions to UNKNOWN; only reconciliation may resolve it. There is no automatic retry from UNKNOWN.

## Mandatory adapter invariants

- The adapter owns the only exchange credential provider.
- No strategy, AI, dashboard, risk, or spool process receives Binance credentials.
- The adapter must validate signature, exact order hash, order ID, account, exchange, environment, symbol, side, quantity, price, notional, expiry, nonce, and policy version itself.
- Idempotency is enforced at the adapter boundary and backed by a database uniqueness constraint; a gate-only check is insufficient.
- Kill switch and account-level halt are re-read immediately before submission.
- Validate Binance symbol status, lot size, tick size, min/max quantity and notional immediately before order construction.
- Client order ID is deterministic and unique per approved order; it is used for reconciliation.
- Disable withdrawals and transfers on exchange credentials. Restrict API key IPs to the adapter egress address.

## Production deployment controls

- Workload identity / secret manager; no .env secret files in source control.
- Separate signing authority and execution verification key.
- PostgreSQL authoritative execution state; Redis may be used only as an acceleration layer, never as the source of truth.
- Persistent global kill switch, default ON at deployment.
- Network policy: execution workload may egress only to required Binance API hosts and approved secret/audit services; all other workloads deny exchange egress.
- Non-root container, read-only root filesystem, dropped Linux capabilities, pinned dependencies/images, SBOM and image signing.
- Health and readiness are distinct. Readiness must verify database, key availability (public key only), kill-switch state, audit integrity, and reconciliation lag.
- Reconciliation worker handles accepted, partial, canceled, rejected, and unknown orders and records canonical fill events.

## Release gates

| Gate | Required evidence | Current status |
|---|---|---|
| Code boundary | Adapter cannot be invoked with proposal/raw approval | NOT VERIFIED |
| Independent approval | Ed25519 signer isolated from execution | NOT VERIFIED |
| Atomic idempotency | DB unique constraints + concurrency tests | Foundation added; tests pending |
| Persistent kill switch | Durable default-halt state and operational drill | NOT VERIFIED |
| Audit | Persistent hash chain + external immutable export | Local chain foundation added; WORM export NOT VERIFIED |
| Reconciliation | Client-order-ID lookup, partial fills, restart recovery | NOT VERIFIED |
| Exchange filters | Live metadata validation and stale-filter rejection | NOT VERIFIED |
| CI/security | Unit, integration, property, concurrency, dependency and image scans | NOT VERIFIED |
| Deployment | VPS runtime, network policy, secret manager, readiness evidence | NOT VERIFIED |
| Mainnet live | Separate explicit approval after all gates PASS | BLOCKED |

## Safety rule

Passing a unit test or deploying a healthy container does not authorize live execution. Live mode remains disabled until independent security review and every release gate is evidenced as PASS.
