# gpogitops

Monorepo for ADMX/GPO policy tooling, JSON policy source-of-truth, and MCP servers.

## Repository layout

- `gpo-json-repo/` — JSON source-of-truth for policy desired state
- `gpo-mcp-server/` — MCP server for GPO workflows and governance
- `admx-mcp-server/` — MCP server for ADMX dictionary/search tooling
- `ms-admx/`, `PolicyDefinitions/`, `ms-policies/` — policy definition and source files
- `Export-ADMXtoJSON.ps1` — helper script for ADMX export/conversion flows

## Quick start

### 1) Validate JSON policy repo

From [gpo-json-repo](gpo-json-repo):

`python3 scripts/validate_json_repo.py --root .`

### 2) Add a new GPO policy

1. Create a policy JSON under [gpo-json-repo/policies](gpo-json-repo/policies).
2. Reference it in [gpo-json-repo/environments/dev/desired-state.json](gpo-json-repo/environments/dev/desired-state.json).
3. Re-run validation.

### 3) Apply policy

- Local registry apply (Windows local machine):
	- [gpo-json-repo/scripts/Apply-DesiredStateLocal.ps1](gpo-json-repo/scripts/Apply-DesiredStateLocal.ps1)
- AD GPO apply (domain GPO via RSAT GroupPolicy):
	- [gpo-json-repo/scripts/Apply-DesiredStateToADGpo.ps1](gpo-json-repo/scripts/Apply-DesiredStateToADGpo.ps1)

## Notes

- `-WhatIf` previews changes without writing.
- Local apply changes machine registry only; it does not update domain GPO objects.
- AD GPO apply must run on Windows with proper domain permissions.
