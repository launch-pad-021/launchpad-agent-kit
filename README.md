# launchpad-agent-kit

Claude Code plugin, deterministic guardrails, reusable agent workflows, and CI templates for Launchpad.

## Layout
```
.claude-plugin/marketplace.json        # this repo is a plugin marketplace with one plugin: "launchpad"
plugins/launchpad/
  .claude-plugin/plugin.json           # only the manifest lives here
  agents/        core agents and specialist reviewers, investigators, release and incident roles
  skills/        spec-to-issues, implement-issue, launchpad-review-gate, release-and-deploy, incident-response
  hooks/hooks.json + hooks/scripts/    session-start, guard-bash, guard-paths, stop-checks
schemas/review.schema.json             # reviewer JSON output (enforced with --json-schema)
schemas/risk.schema.json               # deterministic risk classifier output
scripts/risk.py + test_risk.py         # risk rules and regression tests
.github/workflows/agent-implement.yml  # reusable: implement one issue
.github/workflows/agent-review.yml     # reusable: risk + parallel reviewers → commit statuses
.github/workflows/ci-fix.yml           # reusable: bounded repair of a verified failed CI run
.github/workflows/release.yml          # reusable: release, native multi-arch image, infra PR
templates/ci-*.yml                     # stable Go/Rust/Python/Node/Next required checks
```

## Adopted plugins (not copied here)
superpowers, pr-review-toolkit, code-review, security-guidance, feature-dev, frontend-design, commit-commands, skill-creator, LSP plugins (all `@claude-plugins-official`); Trail of Bits `static-analysis`, `variant-analysis`, `differential-review`, `post-patch-validation`, `insecure-defaults`, `sharp-edges`, `agentic-actions-auditor`; `anthropics/skills` `webapp-testing`. Upstream removed `fix-review`; see `ADOPTED_PLUGINS.md` for the reviewed resolution and immutable pins.

## Use
- Install from GitHub: `/plugin install launchpad --marketplace launch-pad-021/launchpad-agent-kit`. Its dependencies resolve only through the SHA-pinned entries in this marketplace.
- Locally: `claude --plugin-dir ./plugins/launchpad`
- In CI (claude-code-action@v1): `plugin_marketplaces` lists the official, Trail of Bits and this marketplace (newline-separated); `plugins` lists `launchpad@launchpad-agent-kit` plus the adopted plugins; skills are invoked as `/launchpad:<skill>` or `/superpowers:<skill>`.

## Specialist roles

Reviewers inspect supplied diff, test and analysis evidence with read-only tools. The release and incident specialists report a proposed versions.env change and supporting evidence. Their calling workflow owns GitHub writes and deployment gates. The test engineer accepts an assigned branch and caller-enforced test file scope. Reports use the existing reviewer schema.

## Reusable workflow contract

Thin callers pin this repository to an immutable `kit_ref`. Implementer dispatches also pass a nonempty conductor `lease_id`; workflows return that lease and a machine result. Attempts are capped at 3 for implementation, 3 review rounds, and 2 CI fixes. Model calls have explicit turn, budget, and wall-clock limits. Every agent workflow queries the live organization `AGENTS_ENABLED` variable before minting an App token or exposing the model credential. The GitHub App must be configured to read organization variables because the token action has no variables permission-narrowing input.

The caller builds `risk_evidence_json`, `reviewer_evidence_json`, and `merge_evidence_json` from trusted current-head API and Git data, never PR prose. `scripts/select_reviewers.py` emits reviewers in stable §11.2 order. `scripts/merge_gate.py` fails closed unless the six stable checks (`CI / build`, `CI / lint`, `CI / types`, `CI / tests`, `CI / security`, `CI / contracts`), all selected reviews, head freshness, branch freshness, thread state, kill switch, hold state, and risk approval agree. High risk requires developer approval; `agent-config` is always developer-merge-only.

App roles stay separate: developer jobs request contents/PR/issues writes without workflows or administration, reviewer jobs request contents read plus PR/status writes, and the release token is explicitly limited to `launchpad-infra`. Missing secrets, stale heads, forks, held work, exhausted limits, and malformed evidence stop before a writer or merge decision. Live callers must additionally enforce the Apps' installation scope and org-variable access in GitHub.

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

## Hook contract

The four executable entry points under `plugins/launchpad/hooks/scripts/` implement six Claude Code events. The runtime requires POSIX sh, Python 3.9+, Git and a launcher-controlled PATH. SessionStart also requires authenticated GitHub CLI issue and pull-request read access. See the [Claude Code hooks reference](https://code.claude.com/docs/en/hooks).

The launcher sets `CLAUDE_PROJECT_DIR` to the absolute checkout root and `LP_ISSUE_NUMBER` to the assigned positive issue number. Claude supplies the absolute event `cwd` and `agent_type`, for example `launchpad:implementer`. A workflow using the default agent must explicitly export `LP_AGENT_ROLE` from trusted dispatch configuration. When both identities are present they must agree. Issue text, tool arguments and checked-in files cannot set the role. Repository-scoped roles use the repository name from the launcher's `GITHUB_REPOSITORY`, or the checkout directory name locally.

| Event | Behavior |
| --- | --- |
| SessionStart | Supplies a top-level repository map, issue title/body and the latest trusted handoff on the current branch's PR. GitHub text is quoted as data. Secret-like fields are redacted. Missing context, untrusted issue authors and lookup failures return `continue: false`. |
| PreToolUse Bash | Allows a single literal invocation. Supported commands include scoped Git inspection, explicit file staging, commits, feature-branch creation/push, GitHub issue/PR inspection and PR creation, known test commands and fixed package fetches. Read-only roles can inspect changes. The correctness verifier can also run checks. Shell composition, arbitrary executables, direct network access, destructive Git operations and unrecognized options block with exit 2. |
| PreToolUse Edit/Write/MultiEdit | Requires a regular in-workspace file path. Checks new files, existing ancestors, symlinks, hard links, protected configuration, secret material, role and branch scope. Implementers and CI fixers use the assigned agent branch. Test engineers may edit tests, planners may edit their milestone plan, and release/incident agents may edit the infra version manifest. A protected configuration change needs an `agent-config` issue. |
| PostToolUse Edit/Write/MultiEdit | Runs the language formatter on the one authorized file for Go, Rust, Python, TypeScript, JavaScript, CSS and JSON. Formatter failures report a fixed diagnostic. |
| Stop | Runs format, lint/type and unit checks in changed Go, Rust, Python and JS packages. Without a comparison branch it checks every tracked or modified package. A repository without language manifests must expose `make validate` and `make test`. Missing tools, missing checks, timeouts and failures block completion, including on reentry. |
| SubagentStop | Requires the final JSON report sections and finding fields defined in `schemas/review.schema.json`, including at least one check performed. Invalid or secret-like reports block completion. |

Hook subprocesses share a 40-second budget per event. The launcher can shorten it with `LP_HOOK_TIMEOUT_SECONDS` (1–40). The registered 50-second host timeout leaves time to stop the subprocess group and emit the hook decision. Diagnostics show rule names or fixed check commands without forwarding raw child output.

Run project-owned checks only in the job sandbox described in `launchpad-meta/specs/12-agentic-system.md` §6.5. Package managers, tests, formatters and Git can execute project code. Hooks constrain the tool invocation. Filesystem isolation, outbound network policy, token permissions and branch protection are enforced by the runner and GitHub.

## Verify

- `make validate` checks contracts, immutable plugin provenance and dependency wiring, strict Claude manifests, agent/skill discovery, shell syntax, and a clean local plugin load.
- `make test` runs specialist and skill trigger cases, tool-boundary checks, provenance failure cases, offline-first tooling behavior, hook allow/deny decisions, and the risk classifier.
- `make audit-workflows` runs the pinned actionlint release and the strict offline zizmor audit. It requires those packages to be available in the Go/uv caches or network access for first resolution.
- `make verify-provenance` checks every locked commit and component path against GitHub without executing upstream content.
- For a clean install, set a temporary `CLAUDE_CONFIG_DIR`, install `launchpad` from this marketplace, then run `make verify-install` with the same environment; it checks all installed `gitCommitSha` values against the lock.

Anthropic directory publication is not part of A0-02. The public repository currently has no owner-selected license, so directory submission remains blocked until the owner makes that legal choice; GitHub marketplace installation is verified independently.

## Pinned third-party inputs

See `ADOPTED_PLUGINS.md` and `adopted-plugins.lock.json`. The lock records immutable upstream commits, licenses, reviewed executable surfaces, and the resolution for Trail of Bits' removed `fix-review` plugin.

Changes to this repo are `agent-config`: only the developer merges.
