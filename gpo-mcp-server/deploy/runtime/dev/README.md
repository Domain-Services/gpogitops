# Runtime manifests placeholder

This folder should contain Kubernetes manifests (or Helm/Kustomize overlays)
for the environment-specific GPO apply control plane deployed by Argo CD.

Recommended contents:
- `Deployment` for internal GPO apply service
- `CronJob` or `Job` trigger resources (if using pull/apply jobs)
- `Secret` references only (no inline credentials)
- ConfigMap with allowed target OUs/domains and policy bundle location
