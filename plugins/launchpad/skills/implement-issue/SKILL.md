---
name: implement-issue
description: Implement one conductor-dispatched Ready issue in one repository and open its evidence-backed PR. Use when an assigned issue passes readiness. Do not use for planning, review, untracked edits, or multiple issues.
---
# implement-issue (Launchpad glue)

## Trigger boundary

Trigger only for one Ready issue dispatched for implementation. A local edit without an issue, a milestone plan, a review request, or a multi-issue batch does not trigger this skill.

## Evidence sources

Use repository instructions, the assigned issue, its cited spec sections, relevant contracts and code, failing-then-passing tests, and completed verification output. Distinguish observed evidence from claims and list anything not inspected.

This skill only adds Launchpad specifics. Engineering discipline comes from adopted skills — use them as directed below.

1. **Readiness:** check the Definition of Ready (`specs/12-agentic-system.md` §5.3). If not met: comment what's missing, add `agent:blocked`, stop.
2. **Understand:** read the issue, the referenced service spec sections, `specs/03-conventions.md`, and the contracts you touch. For unfamiliar or large changes, use the `feature-dev` plugin's `code-explorer` agent to map the relevant code first.
3. **Build with TDD:** follow superpowers `test-driven-development` — at least one failing test per acceptance criterion before implementation. Branch `agent/<issue>-<slug>`.
4. **Bugs during the work:** follow superpowers `systematic-debugging`; no guess-and-check edits.
5. **Before claiming done:** follow superpowers `verification-before-completion` — run the repo's format/lint/type/test commands and read the output.
6. **Open the PR** using the Launchpad template: acceptance matrix (criterion | implementation | evidence | status), commands with real outcomes, assumptions, follow-ups.
7. **Review feedback:** follow superpowers `receiving-code-review` (verify each finding; fix or reply with evidence). Max 3 rounds, then escalate.
8. **Headless rule:** never use skills that wait for a human (`brainstorming`, `finishing-a-development-branch` merge prompts, `executing-plans` checkpoints). If blocked, write a handoff note and stop.
