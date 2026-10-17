# Production deployment runbook — Binance execution platform

## Current truth

This repository contains a VM deployment workflow at `.github/workflows/deploy-vm.yml`.
A repository commit or successful image build is **not** proof of deployment. A live
execution proof can only be issued after an actual exchange fill is independently
reconciled with exchange order/fill/account state and persisted audit evidence.

**Safe default:** keep `LIVE_TRADING=false` until the Testnet E2E and all preflight
checks are recorded. Never enable real-money orders merely to make a deployment pass.

## Target

The existing workflow targets a Linux VM reachable by SSH. It does not provision
cloud infrastructure. The operator must provision the VM, install Docker, configure
SSH, and create the GitHub Actions Environment named `production`.

## Required GitHub Environment secrets

Configure these in repository Settings → Environments → production → Environment secrets.
Never send secret values in chat or commit them to Git.

- `PRODUCTION_SSH_HOST`: VM hostname or IP
- `PRODUCTION_SSH_USER`: restricted deploy user
- `PRODUCTION_SSH_PRIVATE_KEY`: private key for that deploy user
- `PRODUCTION_SSH_KNOWN_HOSTS`: pinned SSH host key entry
- `EXCHANGE_API_KEY`: exchange key with withdrawals disabled and IP restriction where available
- `EXCHANGE_API_SECRET`: exchange secret
- `APPROVAL_SIGNING_SECRET`: high-entropy application approval-signing secret
- `EXCHANGE_PASSWORD`: only if the chosen exchange requires it; otherwise leave unset

Configure these Environment variables (not secrets):

- `EXCHANGE_ID=binance`
- `LIVE_TRADING=false` (must remain false for first deployment and test validation)

Do not create a Binance key with withdrawal permission. Prefer a dedicated key restricted
to the VM's egress IP and minimum required trading/read permissions.

## VM prerequisites

- Supported Linux VM with Docker Engine and Docker CLI installed
- SSH deploy account restricted to deployment operations; Docker access is effectively root
- Inbound firewall allows SSH only from trusted operator/runner ranges where practical
- Port 8080 is bound to loopback by the workflow; expose it only through a properly
  authenticated reverse proxy if remote health access is required
- Sufficient disk for the Docker image and persistent `trading-state` volume
- Time synchronization enabled
- No secrets in shell history, logs, image layers, or repository files

## Deployment procedure

1. Inspect the exact commit and changes on `deploy/production-evidence-pipeline`.
2. Configure the GitHub Environment secrets/variables above.
3. Trigger Actions → `deploy-production-vm` → Run workflow on the reviewed branch.
4. Confirm image build and remote checksum verification succeeded.
5. Confirm the workflow health-check reports `/readyz` success. Inspect the remote
   container logs for startup/config errors without printing secrets.
6. Confirm the persistent volume and kill-switch path exist. Verify `/var/lib/trading/KILL`
   is present to block execution until an operator deliberately removes it after tests.
7. Keep `LIVE_TRADING=false`; run the testnet end-to-end proof separately. A production
   API key must never be used for testnet.
8. Verify account connectivity, symbol filters, permissions, risk limits, idempotency,
   audit persistence, and recovery/rollback behavior.
9. Only after independent review, deliberately authorize a tiny controlled live order
   with a specific symbol, side, notional cap, maximum loss, and operator approval.
10. Capture the exchange order ID, actual trade/fill IDs, commissions, account state
    before/after, reconciliation result, and audit event IDs.

## Proof artifact contract

Store a JSON record for each deployment/test run with at least:

- `git_commit_sha`, `image_digest`, `deployment_run_url`, `deployment_timestamp_utc`
- `healthz_status`, `readyz_status`, `exchange_connectivity_status`
- `testnet_order_id`, `testnet_trade_ids`, `testnet_reconciliation_status`
- `live_gate_status`, `kill_switch_status`, `risk_policy_version`
- `live_exchange_order_id`, `live_trade_ids`, `executed_quantity`, `average_fill_price`
- `fees`, `account_snapshot_reference`, `reconciliation_id`, `audit_event_id`
- `proof_status`

Use `NOT_RUN`, `BLOCKED`, or `FAIL` when evidence is absent. Never fill evidence
fields with invented values. Set `PRODUCTION_EXECUTION_PROOF=PASS` only when the real
fill is confirmed and the reconciliation/audit chain is complete.

## Important limitation

The connected GitHub tooling can prepare repository changes, but it does not provision
a VM or reveal/configure GitHub Environment secrets. The workflow will not complete until
the operator configures those prerequisites. Do not report deployment success based on
the repository change alone.
