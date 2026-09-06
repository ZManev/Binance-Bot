# Production Trading Security Boundary

This package is the production security boundary for live trading. The existing prototype remains unchanged on `main`.

## Mandatory flow

`AI/Research -> TradeProposal -> RiskEngine -> RiskApproval -> ExecutionGate -> BinanceAdapter -> Binance`

## Non-bypassable invariants

1. AI has no exchange credentials.
2. AI has no Binance network access.
3. Strategy has no exchange credentials.
4. Risk has no exchange credentials.
5. Only the Binance adapter retrieves production exchange credentials.
6. Live orders require valid RiskApproval.
7. Approval is bound to the exact canonical order hash.
8. Approval expires.
9. Every live order passes ExecutionGate.
10. Kill switches are checked immediately before execution.
11. Orders are idempotent.
12. Non-execution services must have no Binance egress.
13. Secrets never live in source, Git, images, logs, DBs, or frontend code.
14. Risk limits are server-side and independent of strategy/AI.
15. Security-sensitive actions are audited.
16. Audit events are tamper-evident.
17. Production credentials are isolated from dev/staging.
18. No component can grant itself execution authority.

## Important deployment note

The current `secrets.py` is an interface boundary. Wire it to Vault or a cloud secrets manager using workload identity. Do not implement it by reading the repository `.env`. The Binance adapter must be the only production workload allowed to retrieve `binance/production/*` secrets.

The default adapter mode is sandbox/testnet. Production live execution must be an explicit deployment configuration and must never be enabled by an AI, strategy, API request, or user-controlled payload.
