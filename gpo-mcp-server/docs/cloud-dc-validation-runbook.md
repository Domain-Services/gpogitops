# Cloud DC validation runbook

This runbook verifies that the production split works end-to-end with a cloud-hosted Domain Controller (DC):

MCP (orchestration) -> Backend API (privileged) -> Bitbucket PR -> CI -> controlled GPO apply validation

## 1) Preflight (control plane)

1. Confirm backend API process is running (`gpo-backend-api`).
2. Confirm MCP process is running (`gpo-mcp-server`).
3. Confirm backend health endpoint returns OK: `GET /healthz`.
4. Confirm MCP is configured with:
   - `GPO_ENFORCE_BACKEND_BOUNDARY=true`
   - `GPO_ALLOW_DIRECT_GIT_WRITES=false`
   - `GPO_BACKEND_API_URL` set
   - `GPO_BACKEND_API_TOKEN` set

## 2) Preflight (cloud DC connectivity)

Run script from a Windows jump host joined to the domain:

- Script: [scripts/windows/Validate-CloudDC-GPO.ps1](../scripts/windows/Validate-CloudDC-GPO.ps1)
- Validates:
  - DNS resolution for DC
  - network reachability
  - SYSVOL accessibility
  - GroupPolicy and ActiveDirectory module presence
  - optional expected GPO existence

## 3) Change-flow smoke test

1. Create one small non-risky XML change in a test policy.
2. Submit change via MCP tool `gpo_submit_change_request` with operation `create_pr_change`.
3. Validate response contains:
   - `change_id`
   - `source_branch`
   - `pull_request.id` and URL
4. Confirm no direct-write path was used (audit logs should show backend flow).

## 4) Bitbucket governance checks

1. Confirm PR target branch is allowed by policy.
2. Confirm reviewer minimum is enforced.
3. Confirm duplicate PR prevention works for same source->target branch pair.
4. Confirm branch protections block direct merge without approvals.

## 5) CI checks

1. Confirm PR triggers Woodpecker.
2. Confirm XML validation and test suite pass.
3. Confirm pipeline evidence is attached to PR.

## 6) Canary apply check (recommended before wider rollout)

1. Link test GPO to a dedicated canary OU only.
2. Force Group Policy refresh on a canary VM.
3. Verify result via RSOP / gpresult.
4. Confirm expected registry values are applied and no unintended settings changed.

## 7) Exit criteria for production confidence

All must pass:
- backend health OK
- cloud DC connectivity script passes
- one end-to-end change request creates governed PR
- CI succeeds
- canary apply verifies intended result only
- audit log includes correlated request trail

## 8) Rollback drill (mandatory)

Perform one rollback simulation:
1. Revert canary policy change via PR.
2. Merge and run apply.
3. Validate policy state returns to previous baseline.
4. Document elapsed recovery time and gaps.
