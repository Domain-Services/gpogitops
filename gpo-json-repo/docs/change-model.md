# Change model

- Every policy is a standalone JSON file in `policies/`.
- Environment manifests in `environments/*/desired-state.json` select policy files.
- Production apply must consume only merged and approved manifests.
- Never apply directly from unmerged branches.
