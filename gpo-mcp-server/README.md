# GPO MCP Server

MCP server for searching and editing GPO XML source files with Git workflow tooling.

## New governance-focused capabilities

- Branch-aware workflow tools:
  - `gpo_create_feature_branch`
  - `gpo_commit_branch_changes`
  - `gpo_create_pull_request`
  - `gpo_submit_change_request`
- Protected branch guardrails for direct commits
- Optional hard disable of direct Git writes from MCP
- Internal backend API integration point for privileged actions
- Bitbucket Cloud pull request creation
- JSONL audit event logging
- Internal backend API runtime (`gpo-backend-api`) for privileged write execution

## Key environment variables

| Variable | Purpose | Default |
|---|---|---|
| `GPO_REPO_PATH` | Local repository path | `/data/gpo-repo` |
| `GPO_REPO_URL` | Remote git URL | unset |
| `GIT_TOKEN` | Git HTTPS token | unset |
| `GPO_ALLOW_DIRECT_GIT_WRITES` | Allow direct MCP push/commit | `false` |
| `GPO_ENFORCE_BACKEND_BOUNDARY` | Block direct git writes and require backend change requests | `true` |
| `GPO_PROTECTED_BRANCHES` | Comma-separated protected branches | `main,master,production,prod` |
| `GPO_DEFAULT_TARGET_BRANCH` | Default PR target | `main` |
| `GPO_ALLOWED_PR_TARGET_BRANCHES` | Comma-separated allowed PR targets | `main` |
| `GPO_BACKEND_API_URL` | Internal privileged API base URL | unset |
| `GPO_BACKEND_API_TOKEN` | Backend API bearer token | unset |
| `GPO_BACKEND_API_HOST` | Backend API bind host | `127.0.0.1` |
| `GPO_BACKEND_API_PORT` | Backend API bind port | `8088` |
| `BITBUCKET_WORKSPACE` | Bitbucket workspace | unset |
| `BITBUCKET_REPO_SLUG` | Bitbucket repository slug | unset |
| `BITBUCKET_TOKEN` | Bitbucket token (`bearer` or `user:app_password`) | unset |
| `GPO_AUDIT_LOG_PATH` | JSONL audit log file path | unset |
| `GPO_ENVIRONMENT` | Environment profile label | `production` |

## Recommended production mode

- Keep `GPO_ENFORCE_BACKEND_BOUNDARY=true`
- Keep `GPO_ALLOW_DIRECT_GIT_WRITES=false`
- Route all privileged writes via `gpo_submit_change_request`
- Keep Bitbucket and backend credentials in secret manager only
- Enforce branch protection and required approvals in Bitbucket

## Running services

- MCP server (orchestration only):
  - `gpo-mcp-server`
- Internal backend API (privileged writes):
  - `gpo-backend-api`

Backend endpoint used by MCP:
- `POST /v1/change-requests`
- Supported operation: `create_pr_change`

Backend health endpoint:
- `GET /healthz`

Cloud DC validation guidance:
- [docs/cloud-dc-validation-runbook.md](docs/cloud-dc-validation-runbook.md)
- Windows validation script: [scripts/windows/Validate-CloudDC-GPO.ps1](scripts/windows/Validate-CloudDC-GPO.ps1)
# gitopsgpo
