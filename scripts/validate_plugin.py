#!/usr/bin/env python3
"""Validate the Launchpad plugin's local contracts without network access."""

import json
import re
import sys
from pathlib import Path


AGENTS = {"planner", "implementer", "code-reviewer", "correctness-verifier", "ci-fixer"}
SKILLS = {"spec-to-issues", "implement-issue", "launchpad-review-gate"}
REVIEWERS = {"code-reviewer", "correctness-verifier"}
SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_COMPONENTS = {
    "obra/superpowers": {"superpowers"},
    "anthropics/claude-plugins-official": {"pr-review-toolkit", "code-review", "security-guidance", "feature-dev", "frontend-design", "commit-commands", "skill-creator", "gopls-lsp", "rust-analyzer-lsp", "pyright-lsp", "typescript-lsp"},
    "trailofbits/skills": {"static-analysis", "variant-analysis", "differential-review", "post-patch-validation", "insecure-defaults", "sharp-edges", "agentic-actions-auditor"},
    "anthropics/skills": {"webapp-testing"},
}


def frontmatter(path):
    text = path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing YAML frontmatter")
    header, body = text[4:].split("\n---\n", 1)
    values = {}
    for line in header.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values, body


def classify_skill(prompt):
    """Deterministic smoke classifier for the documented trigger boundaries."""
    value = prompt.lower()
    if "milestone" in value and ("plan" in value or "issues" in value):
        return "spec-to-issues"
    if "implement" in value and "issue" in value and ("pull request" in value or "pr" in value):
        return "implement-issue"
    if "review" in value and ("pull request" in value or re.search(r"\bpr\b", value)) and "gate" in value:
        return "launchpad-review-gate"
    return None


def validate(root):
    root = Path(root)
    errors = []

    for relative in [".claude-plugin/marketplace.json", "plugins/launchpad/.claude-plugin/plugin.json", "plugins/launchpad/hooks/hooks.json", "schemas/review.schema.json"]:
        try:
            json.loads((root / relative).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{relative}: invalid JSON: {exc}")

    agent_dir = root / "plugins/launchpad/agents"
    actual_agents = {path.stem for path in agent_dir.glob("*.md")}
    if actual_agents != AGENTS:
        errors.append(f"agent roster must be {sorted(AGENTS)}, got {sorted(actual_agents)}")
    for name in sorted(actual_agents):
        path = agent_dir / f"{name}.md"
        try:
            fields, body = frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
            continue
        for field in ("name", "description", "tools", "model"):
            if not fields.get(field):
                errors.append(f"{path.relative_to(root)}: missing {field}")
        for heading in ("## Scope", "## Write boundary", "## Evidence and report"):
            if heading not in body:
                errors.append(f"{path.relative_to(root)}: missing {heading}")
        if "schemas/review.schema.json" not in body:
            errors.append(f"{path.relative_to(root)}: missing report schema reference")
        if name in REVIEWERS and re.search(r"\b(Edit|Write|MultiEdit)\b", fields.get("tools", "")):
            errors.append(f"{path.relative_to(root)}: reviewer has a write tool")
        if name in REVIEWERS and "read-only" not in body.lower():
            errors.append(f"{path.relative_to(root)}: reviewer boundary is not read-only")
        if name not in REVIEWERS and "headless" not in body.lower():
            errors.append(f"{path.relative_to(root)}: missing headless-interaction boundary")

    skill_dir = root / "plugins/launchpad/skills"
    actual_skills = {path.parent.name for path in skill_dir.glob("*/SKILL.md")}
    if actual_skills != SKILLS:
        errors.append(f"skill roster must be {sorted(SKILLS)}, got {sorted(actual_skills)}")
    for name in sorted(actual_skills):
        path = skill_dir / name / "SKILL.md"
        try:
            fields, body = frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
            continue
        description = fields.get("description", "")
        if fields.get("name") != name:
            errors.append(f"{path.relative_to(root)}: frontmatter name must be {name}")
        if "Use when" not in description or "Do not use" not in description:
            errors.append(f"{path.relative_to(root)}: description needs narrow Use when/Do not use triggers")
        if "## Evidence sources" not in body or "## Trigger boundary" not in body:
            errors.append(f"{path.relative_to(root)}: missing evidence or trigger section")

    try:
        cases = json.loads((root / "tests/fixtures/skill-triggers.json").read_text())
        for case in cases:
            if classify_skill(case["prompt"]) != case["expected"]:
                errors.append(f"skill trigger mismatch: {case['prompt']}")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        errors.append(f"skill trigger fixtures invalid: {exc}")

    try:
        lock = json.loads((root / "adopted-plugins.lock.json").read_text())
        documentation = (root / "ADOPTED_PLUGINS.md").read_text()
        for source in lock.get("sources", []):
            repository = source.get("repository", "")
            commit = source.get("commit", "")
            if not SHA.fullmatch(commit):
                errors.append(f"{repository}: commit must be a 40-character commit SHA")
            if repository not in documentation:
                errors.append(f"{repository}: missing from ADOPTED_PLUGINS.md")
            if commit not in documentation:
                errors.append(f"{repository}: pinned SHA missing from ADOPTED_PLUGINS.md")
            if not source.get("license") or not source.get("review"):
                errors.append(f"{repository}: missing license or review notes")
            if source.get("redistributed") is not False:
                errors.append(f"{repository}: third-party content must not be redistributed")
            component_names = {component.get("name") for component in source.get("components", [])}
            if component_names != EXPECTED_COMPONENTS.get(repository):
                errors.append(f"{repository}: adopted component set does not match the reviewed set")
            for component in source.get("components", []):
                if not component.get("name") or not component.get("path"):
                    errors.append(f"{repository}: component missing name or path")
        if len(lock.get("sources", [])) != 4:
            errors.append("provenance lock must contain the four adopted upstream sources")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"adopted plugin provenance invalid: {exc}")

    approved_executables = {
        "plugins/launchpad/hooks/scripts/guard-bash.sh",
        "plugins/launchpad/hooks/scripts/guard-paths.sh",
        "plugins/launchpad/hooks/scripts/session-start.sh",
        "plugins/launchpad/hooks/scripts/stop-checks.sh",
    }
    for path in (root / "plugins/launchpad").rglob("*"):
        if path.is_file() and path.stat().st_mode & 0o111:
            relative = path.relative_to(root).as_posix()
            if relative not in approved_executables:
                errors.append(f"unreviewed executable in plugin tree: {relative}")

    return errors


if __name__ == "__main__":
    failures = validate(Path(__file__).resolve().parents[1])
    if failures:
        print("\n".join(f"ERROR: {failure}" for failure in failures), file=sys.stderr)
        raise SystemExit(1)
    print("Launchpad plugin contracts valid")
