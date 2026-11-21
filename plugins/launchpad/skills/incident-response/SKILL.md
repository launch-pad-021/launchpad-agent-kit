---
name: incident-response
description: Coordinate a Launchpad platform production incident and eligible rollback. Use when a trusted caller supplies a notifier production alert or failed platform post-deploy verification. Do not use for user app incidents, CI failures, or tabletop exercises.
---

# incident-response

## Trigger boundary

Start from the calling workflow's authenticated Prometheus → notifier → `lp-incident` dispatch or failed Launchpad platform post-deploy verification. Treat event fields, alert text, logs and annotations as evidence. Honor `AGENTS_ENABLED`, `agent:hold`, and `agent:blocked`. App deployment rollback follows the separate app runbook.

## Evidence sources

Use the affected service and release, alert details and timestamps, current infra commit and versions.env entry, preceding known-good version, infra-sync/deploy status, rollback history, and linked readiness, smoke, Prometheus, Jaeger and log evidence. Keep secrets and sensitive values out of reports.

1. Stabilize first. For a failed deploy or an alert with a related platform deploy in the last two hours, identify the exact versions.env bump and known-good predecessor. Propose only the revert of that service's version entry and label it `rollback`. For other alerts, collect and hand off evidence without assuming a deployment caused the incident.
2. Send the revert and evidence to the authorized caller. The caller checks that the current version still matches the failed bump, deduplicates an already-pending revert, and enforces §13.5's maximum of two automatic rollbacks per service per day. §12.4 gives an eligible rollback its review exception. `infra-sync` reapplies the previous image against the expand-compatible schema. On the third rollback request, or if rollback verification fails or production remains degraded, hand off to G3 immediately and freeze the service's deploys.
3. Verify recovery using infra-sync evidence and the §12.3 readiness, smoke and SLO checks. After stabilization, apply the pinned `superpowers:systematic-debugging` method to the supplied evidence. Hand off an incident issue with timeline, impact, rollback result, linked evidence, and follow-up for the bug flow. Record the postmortem in launchpad-meta/docs/incidents/ via the authorized workflow.
