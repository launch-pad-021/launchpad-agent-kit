# launchpad-agent-kit (starter)

Claude Code plugin + reusable workflows for building Launchpad with agents. This is the **starter** shipped in the spec pack; milestone **A0** completes it (`launchpad-meta/specs/11-delivery-plan.md`).

## Layout
```
.claude-plugin/marketplace.json        # this repo is a plugin marketplace with one plugin: "launchpad"
plugins/launchpad/
  .claude-plugin/plugin.json           # only the manifest lives here
  agents/        planner, implementer, code-reviewer, correctness-verifier, ci-fixer   (+12 more in A0-06)
  skills/        spec-to-issues, implement-issue, launchpad-review-gate   (Launchpad glue only; engineering skills come from adopted plugins)
  hooks/hooks.json + hooks/scripts/    session-start, guard-bash, guard-paths, stop-checks
schemas/review.schema.json             # reviewer JSON output (enforced with --json-schema)
schemas/risk.schema.json               # deterministic risk classifier output
scripts/risk.py + test_risk.py         # risk rules and regression tests
.github/workflows/agent-implement.yml  # reusable: implement one issue
.github/workflows/agent-review.yml     # reusable: risk + parallel reviewers → commit statuses
```

## Adopted plugins (not copied here)
superpowers, pr-review-toolkit, code-review, security-guidance, feature-dev, frontend-design, commit-commands, skill-creator, LSP plugins (all `@claude-plugins-official`); Trail of Bits `static-analysis`, `variant-analysis`, `differential-review`, `post-patch-validation`, `insecure-defaults`, `sharp-edges`, `agentic-actions-auditor`; `anthropics/skills` `webapp-testing`. Upstream removed `fix-review`; see `ADOPTED_PLUGINS.md` for the reviewed resolution and immutable pins.

## Use
- Install from GitHub: `/plugin install launchpad --marketplace launch-pad-021/launchpad-agent-kit`. Its dependencies resolve only through the SHA-pinned entries in this marketplace.
- Locally: `claude --plugin-dir ./plugins/launchpad`
- In CI (claude-code-action@v1): `plugin_marketplaces` lists the official, Trail of Bits and this marketplace (newline-separated); `plugins` lists `launchpad@launchpad-agent-kit` plus the adopted plugins; skills are invoked as `/launchpad:<skill>` or `/superpowers:<skill>`.

## Risk classifier

Run `python3 scripts/risk.py --input evidence.json`, or pass `--input -` to read JSON from stdin. Generate evidence from the reviewed Git diff and trusted checks. Keep issue and PR text out of evidence generation.

| Field | Required evidence |
| --- | --- |
| `repo` | The bare repository name, such as `launchpad-deployer`. |
| `files` | Nonempty array of literal Git paths relative to the repository. Include deleted paths and both sides of renames. Preserve whitespace, quotes, and backslashes. |
| `diff` | `changed_lines` is the number of added and removed lines. `new_service_call`, `new_event`, and `security_sensitive` are boolean assessments of the diff. `security_sensitive` covers §11.1 security areas outside canonical paths and edits to `versions.env` that are more than version bumps. |
| `labels` | Array of GitHub label names. The `agent-config` label sets `agent_config` and raises risk to high. Risk labels can only raise the result. |
| `dependencies` | Array of `{ "name": "…", "change": "…" }` entries. Values for `change` are `new`, `major`, `minor`, `patch`, `removed`, and `unknown`. Use a unique name per dependency and an empty array when no dependencies changed. |
| `contracts` | `none`, `additive`, `breaking`, or `unknown`. Use the result of the compatibility check for changed contracts. |
| `migrations` | Object mapping each changed migration path to `non_destructive`, `destructive`, or `unknown`. Use an empty object when no migrations changed. |

Set an unavailable diff assessment to `null`. Missing, invalid, or inconclusive evidence yields `risk/high`. The classifier writes a single JSON report with `level`, `status`, `agent_config`, and `reasons` after validating it against `schemas/risk.schema.json`. The starter CLI options still accept path and label evidence and yield high risk until the complete input is supplied. The starter Python `classify()` function remains available for local callers using partial evidence.

## Verify

- `make validate` checks contracts, immutable plugin provenance and dependency wiring, strict Claude manifests, agent/skill discovery, shell syntax, and a clean local plugin load.
- `make test` runs trigger boundaries, provenance failure cases, offline-first tooling behavior, and the risk classifier.
- `make verify-provenance` checks every locked commit and component path against GitHub without executing upstream content.
- For a clean install, set a temporary `CLAUDE_CONFIG_DIR`, install `launchpad` from this marketplace, then run `make verify-install` with the same environment; it checks all installed `gitCommitSha` values against the lock.

Anthropic directory publication is not part of A0-02. The public repository currently has no owner-selected license, so directory submission remains blocked until the owner makes that legal choice; GitHub marketplace installation is verified independently.

## Pinned third-party inputs

See `ADOPTED_PLUGINS.md` and `adopted-plugins.lock.json`. The lock records immutable upstream commits, licenses, reviewed executable surfaces, and the resolution for Trail of Bits' removed `fix-review` plugin.

Changes to this repo are `agent-config`: only the developer merges.
