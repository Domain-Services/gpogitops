# Enterprise roadmap (incremental)

## Current state (implemented)

- MCP tools for XML search/edit
- Git sync/commit/push
- New branch workflow tools
- Protected branch guardrails
- Optional direct-write disable
- Backend API change-request integration point
- Bitbucket PR create capability
- Audit event logging hook
- Woodpecker pipeline baseline
- Argo CD application skeleton

## Next implementation slices

1. **Backend API contract stabilization**
   - Define strict schema for `/v1/change-requests`
   - Add server-side authorization and policy checks
   - Return signed change IDs for traceability

2. **Policy-as-code gates**
   - Path allowlists, XML schema and semantic checks
   - Risk scoring (low/medium/high) by touched settings
   - Reviewer requirements by risk level

3. **CI/CD hardening**
   - Generate signed deployment bundles
   - Add provenance attestation and SBOM
   - Promotion by pull request to env repos (`dev` → `test` → `prod`)

4. **Runtime delivery isolation**
   - Dedicated apply service inside privileged network boundary
   - JIT credentials to AD/GPO runtime
   - Dry-run and rollback support

5. **Audit and incident response**
   - Centralize JSONL events into SIEM
   - Alert on unusual change patterns
   - Add replay-safe idempotency controls
