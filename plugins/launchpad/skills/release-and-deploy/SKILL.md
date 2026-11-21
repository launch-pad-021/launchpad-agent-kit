---
name: release-and-deploy
description: Coordinate a Launchpad platform release and post-deploy verification. Use when a trusted caller supplies a published platform image or completed infra-sync deploy. Do not use for customer apps, previews, or direct host operations.
---

# release-and-deploy

## Trigger boundary

Use for Launchpad platform services with a workflow-verified publication or infra-sync event. Preview deployments and apps deployed by Launchpad follow their own flows. The caller performs GitHub writes. The server-side infra-sync process performs deployment.

## Evidence sources

Use the release-please release PR and tag, linked changelog, migration notes, GHCR image manifest and provenance, current launchpad-infra versions.env, deploy commit and infra-sync/deploy status, readiness results, smoke runs, and Prometheus baseline and watch links.

1. For publication, verify that the release-please tag has a GHCR manifest for native arm64 and amd64 images with provenance. Identify the current version and exact rollback target. Prepare a launchpad-infra PR changing only the service's versions.env entry. Include changelog, migration note and rollback target. A pure version bump is low risk, a migration is medium, and a high-risk release remains high. The caller applies §11 merge policy and the current autonomy phase (§22).
2. Match infra-sync/deploy to the exact infra commit. The server applies only changed services in dependency order and runs expand migrations in a one-shot container before the new service starts. The destructive contract step is a separate release. Inspect evidence through the calling workflow.
3. For a completed deploy, verify `/readyz` for the service and direct dependents, an affected-flow smoke E2E run, and 15 minutes of Prometheus error rate, p95 latency, consumer lag, and outbox backlog relative to the previous version where applicable. The caller may mark Verified only with passing evidence.
4. On failed verification, hand off to incident-response with links for the failing check, affected service, infra commit, and previous version. Report missing status, artifacts or watch data as unknown. Never infer a passing deployment.
