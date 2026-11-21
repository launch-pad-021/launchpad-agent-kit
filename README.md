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
scripts/risk.py + test_risk.py         # deterministic risk classifier (16 tests)
.github/workflows/agent-implement.yml  # reusable: implement one issue
.github/workflows/agent-review.yml     # reusable: risk + parallel reviewers → commit statuses
```

## Adopted plugins (not copied here)
superpowers, pr-review-toolkit, code-review, security-guidance, feature-dev, frontend-design, commit-commands, skill-creator, LSP plugins (all `@claude-plugins-official`); Trail of Bits `static-analysis`, `variant-analysis`, `differential-review`, `post-patch-validation`, `insecure-defaults`, `sharp-edges`, `agentic-actions-auditor`; `anthropics/skills` `webapp-testing`. Upstream removed `fix-review`; see `ADOPTED_PLUGINS.md` for the reviewed resolution and immutable pins.

## Use
- Install from GitHub: `/plugin install launchpad --marketplace launch-pad-021/launchpad-agent-kit`. Its dependencies resolve only through the SHA-pinned entries in this marketplace.
- Locally: `claude --plugin-dir ./plugins/launchpad`
- In CI (claude-code-action@v1): `plugin_marketplaces` lists the official, Trail of Bits and this marketplace (newline-separated); `plugins` lists `launchpad@launchpad-agent-kit` plus the adopted plugins; skills are invoked as `/launchpad:<skill>` or `/superpowers:<skill>`.

## Verify

- `make validate` checks contracts, immutable plugin provenance and dependency wiring, strict Claude manifests, agent/skill discovery, shell syntax, and a clean local plugin load.
- `make test` runs trigger boundaries, provenance failure cases, offline-first tooling behavior, and the risk classifier.
- `make verify-provenance` checks every locked commit and component path against GitHub without executing upstream content.
- For a clean install, set a temporary `CLAUDE_CONFIG_DIR`, install `launchpad` from this marketplace, then run `make verify-install` with the same environment; it checks all installed `gitCommitSha` values against the lock.

Anthropic directory publication is not part of A0-02. The public repository currently has no owner-selected license, so directory submission remains blocked until the owner makes that legal choice; GitHub marketplace installation is verified independently.

## Pinned third-party inputs

See `ADOPTED_PLUGINS.md` and `adopted-plugins.lock.json`. The lock records immutable upstream commits, licenses, reviewed executable surfaces, and the resolution for Trail of Bits' removed `fix-review` plugin.

Changes to this repo are `agent-config`: only the developer merges.
