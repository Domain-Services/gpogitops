# GPO JSON Source Repository

GitOps source-of-truth for GPO changes represented as JSON.

## Structure

- `schema/` JSON schema definitions for policy documents
- `policies/` reusable policy objects (one policy per file)
- `environments/` environment desired-state manifests
- `scripts/` validation/build helpers
- `docs/` operational runbooks

## Workflow

1. Edit or add JSON policy files under `policies/`.
2. Reference policies from an environment manifest under `environments/<env>/desired-state.json`.
3. Open PR with reviewers.
4. CI validates schema and policy references.
5. Backend/apply service consumes approved environment manifest.

## Create a new policy

1. Create a new file under `policies/` (example: `policies/disable-registry-tools.json`).
2. Use this shape:
	 - `id` (unique string)
	 - `name`
	 - `path` (logical category)
	 - `settings[]` with:
		 - `registry_path`
		 - `value_name`
		 - `value_type`
		 - `value`
3. Add the policy file path to `environments/<env>/desired-state.json` under `policies`.

Reference schema: `schema/gpo-policy.schema.json`.

## Validate JSON repo

Run:

`python3 scripts/validate_json_repo.py --root .`

## Apply modes

### 1) Local machine registry only (no AD GPO changes)

Use:

`scripts/Apply-DesiredStateLocal.ps1`

Example:

`./scripts/Apply-DesiredStateLocal.ps1 -RepoRoot . -Environment dev -WhatIf`

Then apply:

`./scripts/Apply-DesiredStateLocal.ps1 -RepoRoot . -Environment dev`

This writes registry values on the local machine only.

### 2) Active Directory GPO update

Use:

`scripts/Apply-DesiredStateToADGpo.ps1`

Example (preview):

`./scripts/Apply-DesiredStateToADGpo.ps1 -RepoRoot . -Environment dev -GpoName "Dev Baseline" -CreateIfMissing -LinkToTargetOU -WhatIf`

Apply:

`./scripts/Apply-DesiredStateToADGpo.ps1 -RepoRoot . -Environment dev -GpoName "Dev Baseline" -CreateIfMissing -LinkToTargetOU`

Requirements:
- Windows host
- RSAT GroupPolicy module
- Permissions to create/edit/link GPOs

## Verify expected result

After AD apply:
- Check GPO exists in GPMC.
- Check registry settings exist in that GPO.
- If linked, confirm link to manifest `target_ou`.
- On target client, run `gpupdate /force` and validate effective policy.
