---
name: launchpad-review-gate
description: Convert an assigned Launchpad PR review into the merge-gate JSON schema. Use when the agent-review workflow supplies a PR and reviewer role. Do not use to implement fixes, self-review, or provide informal feedback.
---
# launchpad-review-gate

## Trigger boundary

Trigger only for an assigned pull request and explicit reviewer role in the Launchpad merge gate. General code questions, implementation work, self-review, and informal feedback do not trigger this skill.

## Evidence sources

Use the base-to-head diff, linked issue criteria, applicable contracts/specs, completed CI runs, and role-specific analyzer output. Every finding needs file/line evidence, a concrete trigger and impact; record checks and uninspected areas.

1. Determine your reviewer role from the prompt (code, security, design, database, docs, deps, correctness).
2. Apply the matching adopted review method to the PR diff (`origin/<base>...HEAD`). The calling workflow runs adopted specialist agents in separate read-only jobs and may supply their evidence; this skill does not spawn nested agents:
   | Role | Use |
   |---|---|
   | code | `pr-review-toolkit` agents (code, tests, silent failures, types) + `code-review` |
   | security | Trail of Bits `differential-review`, `insecure-defaults`, `sharp-edges`; `security-guidance` review; check `specs/08-security.md` controls for touched areas |
   | agent-config | Trail of Bits `agentic-actions-auditor` on changed workflows |
   | design | `frontend-design` principles + `webapp-testing` screenshots at 375/768/1280 |
   | database | `specs/05-data.md` §6 expand/contract rules; `EXPLAIN` evidence for query changes |
   | correctness | map each acceptance criterion in the linked issue to a test and a passing CI job (superpowers `verification-before-completion` standard) |
3. Add Launchpad checks the adopted tools don't know: conformance to `contracts/` and `specs/03-conventions.md` (errors, envelope, outbox, config, logging), and the service spec's acceptance criteria.
4. Keep only findings with a concrete file/line, trigger and impact. Drop low-confidence findings rather than guessing.
5. Output **only** JSON matching `schemas/review.schema.json` (`specs/12-agentic-system.md` §9.3). Use `needs_human` when the change is high risk or outside what you can judge.
