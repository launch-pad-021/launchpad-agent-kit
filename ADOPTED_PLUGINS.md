# Adopted plugin provenance

The machine-readable source of truth is `adopted-plugins.lock.json`. All sources are immutable commit pins. The Launchpad marketplace exposes each reviewed component from its exact `sha`, and the `launchpad` entry declares them as same-marketplace dependencies. Installing `launchpad@launchpad-agent-kit` therefore resolves the reviewed commits rather than upstream marketplace HEAD. We do not copy third-party content into this repository.

| Source | Pinned commit | License | Review disposition |
|---|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers/tree/22f0b463e7a5e579904dd6211a520321035526f7) | `22f0b463e7a5e579904dd6211a520321035526f7` | MIT | Skills, hooks, and helpers reviewed. Interactive skills are local-only and forbidden in headless runs. |
| [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/73c8cf3ea7e296057b467990f2f5d61b4c922260) | `73c8cf3ea7e296057b467990f2f5d61b4c922260` | Apache-2.0 | Requested manifests, agents, skills, hooks, scripts, and permissions reviewed. Commit commands are local-only; reviewers remain read-only. |
| [trailofbits/skills](https://github.com/trailofbits/skills/tree/149d7b21f4067765b82e67029730b42d228ef4b4) | `149d7b21f4067765b82e67029730b42d228ef4b4` | CC-BY-SA-4.0 | Analysis instructions, workflows, scripts, and external-tool use reviewed; review jobs are read-only. |
| [anthropics/skills](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba) | `e4bb5d960d87126ff3b3a8af1a104b7db67560ba` | Apache-2.0 for `webapp-testing` | `with_server.py` may start explicitly supplied local servers; use only in isolated dashboard review with test data. |

## Component decisions

- Official marketplace: `pr-review-toolkit`, `code-review`, `security-guidance`, `feature-dev`, `frontend-design`, `commit-commands`, `skill-creator`, `gopls-lsp`, `rust-analyzer-lsp`, `pyright-lsp`, and `typescript-lsp`.
- Trail of Bits: `static-analysis`, `variant-analysis`, `differential-review`, `post-patch-validation`, `insecure-defaults`, `sharp-edges`, and `agentic-actions-auditor`.
- Anthropic skills: `webapp-testing`.
- Superpowers: the engineering workflow skills named in the Launchpad spec; `brainstorming`, `finishing-a-development-branch`, and interactive `executing-plans` checkpoints must not run headlessly.

## Upstream drift resolved during review

`trailofbits/skills` removed `fix-review` in commit `15f6b1c8801f3b35e094cc464ff0d797018135cc`, stating that it was internal-only and had been published by mistake. The pinned public tree therefore uses `post-patch-validation` for fix verification. This is an explicit compatibility resolution, not an unpinned substitution.

## Update procedure

1. Resolve a new full commit SHA from the upstream repository.
2. Inspect the affected manifests, instructions, hooks, scripts, permissions, license, and newly introduced executable files.
3. Update both provenance files and run `make validate test`.
4. Merge only through an `agent-config` pull request approved by the developer.
