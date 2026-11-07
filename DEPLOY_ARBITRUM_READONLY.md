# Arbitrum One — Linux VPS READ-ONLY deployment

This runbook deploys the FastAPI research dashboard only. It does not enable live trading.

## Target infrastructure

Recommended initial provider: Scaleway Virtual Instances, Amsterdam region (AMS1), general-purpose class. A 4-vCPU / 16-GB instance is a reasonable starting size for this single API container. Confirm exact SKU availability, attached storage, public IPv4, backups, taxes and final checkout price before ordering.

The service is bound to host loopback only (`127.0.0.1:8787`). Access it through an SSH tunnel or a separately reviewed authenticated reverse proxy. Do not expose port 8787 directly to the public internet.

## Provisioning baseline

- Ubuntu Server 24.04 LTS (or current supported LTS image).
- 4 vCPU, 16 GB RAM, at least 80 GB SSD/NVMe.
- Dedicated non-root deployment account; SSH key authentication.
- Cloud firewall: allow SSH only from trusted operator IPs; deny public ingress to 8787.
- Enable unattended security updates and time synchronization.
- Install Docker Engine and the Docker Compose plugin from Docker's official repository.
- Configure provider snapshots/backups and host-level monitoring.

## Configure secrets locally on the VPS

From the repository checkout on the deployment branch:

```bash
cp .env.arbitrum-readonly.example .env.arbitrum-readonly
chmod 600 .env.arbitrum-readonly
editor .env.arbitrum-readonly
```

Set `ARBITRUM_RPC_URL` to a trusted HTTPS endpoint. The public Arbitrum RPC in the example is a smoke-test fallback, not a production SLA commitment. Set `AAVE_V3_ADDRESSES_PROVIDER` from the official Aave Address Book for Arbitrum One. Never commit the real env file.

## Validate and start

```bash
docker compose -f compose.arbitrum-readonly.yml config --quiet
docker compose -f compose.arbitrum-readonly.yml build --pull
docker compose -f compose.arbitrum-readonly.yml up -d
docker compose -f compose.arbitrum-readonly.yml ps
curl -fsS http://127.0.0.1:8787/api/health
curl -fsS http://127.0.0.1:8787/api/mainnet/readiness
```

Expected safety fields remain false: `execution_ready`, `signing_enabled`, `transaction_submission_enabled`, and `deployment_enabled`. Readiness checks may legitimately report NOT_CONFIGURED / NOT_RUN until valid provider settings are supplied. A bytecode check is not ABI, liquidity, live quote, profitability, or execution verification.

View logs without printing environment variables:

```bash
docker compose -f compose.arbitrum-readonly.yml logs --tail=100 arbitrum-readonly-api
```

Use an SSH tunnel from the operator workstation:

```bash
ssh -N -L 8787:127.0.0.1:8787 <deploy-user>@<vps-host>
```

Then open `http://127.0.0.1:8787` locally.

## Security controls in the container

- Non-root UID 10001.
- Read-only container root filesystem; writable temporary filesystem only.
- All Linux capabilities dropped; no-new-privileges enabled.
- CPU, memory and PID limits.
- Loopback-only published port.
- No signer, private key, wallet, transaction builder or write-capable RPC methods.

## Mandatory blockers before any production deployment

1. Rotate every credential that was ever committed to repository history. Removing a file in a later commit does not revoke credentials or erase old Git objects. Complete history remediation and verify the repository scan before deploying.
2. Confirm the current branch CI is green on its latest commit.
3. Independently verify the Aave provider address and RPC provider account.
4. Confirm provider location, SKU, invoice, backup policy and firewall before provisioning.
5. Do not add signing, transaction submission, contract deployment or live execution to this deployment profile. Any future change requires separate explicit approval and a distinct security review.

## Rollback

```bash
docker compose -f compose.arbitrum-readonly.yml down
```

This removes the container but leaves the repository and local env file intact. Preserve sanitized logs and the deployment evidence report for audit.
