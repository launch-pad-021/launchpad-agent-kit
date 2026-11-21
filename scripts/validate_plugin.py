#!/usr/bin/env python3
"""Validate the Launchpad plugin's local contracts without network access."""

import json
import re
import sys
from pathlib import Path


CORE_AGENTS = {"planner", "implementer", "code-reviewer", "correctness-verifier", "ci-fixer"}
OPERATIONAL_SKILLS = {"release-and-deploy", "incident-response"}
SKILLS = {"spec-to-issues", "implement-issue", "launchpad-review-gate"} | OPERATIONAL_SKILLS
SPECIALIST_TRIGGERS = {
    "pull_request": {
        "security-auditor": {"security path", "auth", "input handling", "new endpoint"},
        "architecture-reviewer": {"contract", "new service", "new dependency", "data ownership"},
        "database-reviewer": {"migration", "sql", "clickhouse schema"},
        "product-design-reviewer": {"dashboard ui"},
        "documentation-auditor": {"api change", "config change", "behavior change"},
        "dependency-supply-chain-auditor": {"dependency pr"},
    },
    "weekly": {
        "security-auditor": {"security scan"},
        "documentation-auditor": {"documentation sweep"},
        "dependency-supply-chain-auditor": {"advisory sweep"},
    },
    "agent handoff": {
        "test-engineer": {"test handoff"},
        "debugging-investigator": {"incident investigation"},
    },
    "issue": {
        "test-engineer": {"coverage gap"},
        "debugging-investigator": {"bug issue"},
        "performance-investigator": {"perf-labelled issue"},
    },
    "alert": {
        "performance-investigator": {"performance regression"},
        "incident-responder": {"production alert"},
    },
    "release": {
        "release-manager": {"image is published", "deploy finished"},
        "incident-responder": {"failed verification"},
    },
    "request": {"technical-researcher": {"latest or best", "primary-source adr"}},
}
SPECIALISTS = {role for event in SPECIALIST_TRIGGERS.values() for role in event}
AGENTS = CORE_AGENTS | SPECIALISTS
SPECIALIST_MODELS = {
    "security-auditor": "opus",
    "architecture-reviewer": "opus",
    "database-reviewer": "sonnet",
    "product-design-reviewer": "sonnet",
    "documentation-auditor": "haiku",
    "dependency-supply-chain-auditor": "haiku",
    "performance-investigator": "sonnet",
    "debugging-investigator": "sonnet",
    "release-manager": "sonnet",
    "incident-responder": "opus",
    "technical-researcher": "sonnet",
    "test-engineer": "sonnet",
}
REVIEW_GATE = "launchpad:launchpad-review-gate"
VERIFY = "superpowers:verification-before-completion"
DEBUG = "superpowers:systematic-debugging"
WEB_SPECIALISTS = {"technical-researcher", "dependency-supply-chain-auditor"}
REVIEWERS = {"code-reviewer", "correctness-verifier"}
SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_COMPONENTS = {
    "obra/superpowers": {"superpowers": "."},
    "anthropics/claude-plugins-official": {name: f"plugins/{name}" for name in ("pr-review-toolkit", "code-review", "security-guidance", "feature-dev", "frontend-design", "commit-commands", "skill-creator", "gopls-lsp", "rust-analyzer-lsp", "pyright-lsp", "typescript-lsp")},
    "trailofbits/skills": {name: f"plugins/{name}" for name in ("static-analysis", "variant-analysis", "differential-review", "post-patch-validation", "insecure-defaults", "sharp-edges", "agentic-actions-auditor")},
    "anthropics/skills": {"webapp-testing": "skills/webapp-testing"},
}
AGENT_SKILLS = {
    "planner": {"spec-to-issues", "superpowers:writing-plans"},
    "implementer": {"implement-issue", "superpowers:test-driven-development", "superpowers:systematic-debugging", "superpowers:verification-before-completion", "superpowers:receiving-code-review"},
    "ci-fixer": {"superpowers:systematic-debugging", "superpowers:verification-before-completion"},
    "code-reviewer": {"launchpad-review-gate"},
    "correctness-verifier": {"launchpad-review-gate", VERIFY},
    "security-auditor": {REVIEW_GATE, "differential-review:differential-review", "sharp-edges:sharp-edges"},
    "architecture-reviewer": {REVIEW_GATE},
    "database-reviewer": {REVIEW_GATE, VERIFY},
    "product-design-reviewer": {REVIEW_GATE, "frontend-design:frontend-design"},
    "documentation-auditor": {REVIEW_GATE, VERIFY},
    "dependency-supply-chain-auditor": {REVIEW_GATE, VERIFY},
    "performance-investigator": {DEBUG, VERIFY},
    "debugging-investigator": {DEBUG},
    "release-manager": {"launchpad:release-and-deploy", VERIFY},
    "incident-responder": {"launchpad:incident-response", DEBUG},
    "technical-researcher": {VERIFY},
    "test-engineer": {"superpowers:test-driven-development", VERIFY},
}


def frontmatter(path):
    text = path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing YAML frontmatter")
    header, body = text[4:].split("\n---\n", 1)
    values = {}
    for line in header.splitlines():
        key, separator, value = line.partition(":")
        if not separator or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]*", key):
            raise ValueError(f"unsupported frontmatter line: {line}")
        if key in values:
            raise ValueError(f"duplicate frontmatter field: {key}")
        values[key] = value.strip()
    return values, body


def classify_skill(prompt, descriptions):
    """Deterministic smoke classifier for the documented trigger boundaries."""
    value = prompt.lower()
    planning_exclusion = any(phrase in value for phrase in ("do not plan", "don't plan", "implement code", "single issue", "one issue", "ad-hoc design", "not an issue plan"))
    implementation_exclusion = any(phrase in value for phrase in ("do not implement", "don't implement", "not ready", "multiple issues", "implement issues", "review this pr", "review pr"))
    review_exclusion = any(phrase in value for phrase in ("informally", "informal feedback", "do not use", "don't use", "my own pr", "self-review", "implement fixes", "write fixes"))
    if not planning_exclusion and "milestone" in value and ("plan" in value or "issues" in value) and all(word in descriptions.get("spec-to-issues", "").lower() for word in ("milestone", "plan")):
        return "spec-to-issues"
    if not implementation_exclusion and "implement" in value and "issue" in value and ("pull request" in value or "pr" in value) and all(word in descriptions.get("implement-issue", "").lower() for word in ("implement", "issue", "pr")):
        return "implement-issue"
    if not review_exclusion and "review" in value and ("pull request" in value or re.search(r"\bpr\b", value)) and "gate" in value and all(word in descriptions.get("launchpad-review-gate", "").lower() for word in ("review", "pr", "gate")):
        return "launchpad-review-gate"
    operational_exclusion = any(
        phrase in value for phrase in ("do not", "don't", "tabletop", "preview", "customer app", "user app", "staging")
    )
    if "launchpad" in value and not operational_exclusion:
        incident = descriptions.get("incident-response", "").lower()
        if "production alert" in incident and "post-deploy verification" in incident and (
            ("production alert" in value and "notifier" in value)
            or ("post-deploy verification" in value and "failed" in value)
        ):
            return "incident-response"
        release = descriptions.get("release-and-deploy", "").lower()
        if "platform image" in release and "infra-sync deploy" in release and (
            ("published platform image" in value and "versions.env" in value)
            or ("verify" in value and "platform deploy" in value and "infra-sync" in value)
        ):
            return "release-and-deploy"
    return None


def classify_specialists(event, conditions, descriptions, *, trusted=True):
    """Exercise documented specialist triggers with fixture facts, without dispatching agents."""
    if not trusted:
        return set()
    conditions = {condition.lower() for condition in conditions}
    selected = set()
    for role, triggers in SPECIALIST_TRIGGERS.get(event, {}).items():
        description = descriptions.get(role, "").lower()
        use_clause = description.partition("do not use")[0]
        if any(re.search(rf"\b{re.escape(trigger)}\b", use_clause) for trigger in conditions & triggers):
            selected.add(role)
    return selected


def specialist_errors(name, fields, body):
    errors = []
    for field in sorted(fields.keys() - {"name", "description", "tools", "model", "skills"}):
        errors.append(f"unsupported frontmatter field: {field}")
    description = fields.get("description", "")
    if "Use when" not in description or "Do not use" not in description:
        errors.append("description needs narrow Use when/Do not use triggers")
    if fields.get("model") != SPECIALIST_MODELS[name]:
        errors.append("model does not match the specified tier")

    allowed = {"Read", "Grep", "Glob"}
    if name in WEB_SPECIALISTS:
        allowed |= {"WebSearch", "WebFetch"}
    if name == "test-engineer":
        allowed |= {"Edit", "Write"}
    tools = {tool.strip() for tool in fields.get("tools", "").split(",")}
    if tools != allowed:
        errors.append("tool allowlist must match the test-only role" if name == "test-engineer" else "role must use only its read-only tools")
    if name != "test-engineer" and "read-only" not in body.lower():
        errors.append("role boundary is not read-only")
    return errors


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
    agent_descriptions = {}
    for name in sorted(actual_agents):
        path = agent_dir / f"{name}.md"
        try:
            fields, body = frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
            continue
        agent_descriptions[name] = fields.get("description", "")
        if fields.get("name") != name:
            errors.append(f"{path.relative_to(root)}: frontmatter name must be {name}")
        if name in SPECIALISTS:
            errors.extend(f"{path.relative_to(root)}: {error}" for error in specialist_errors(name, fields, body))
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
        declared_skills = {item.strip().strip('"\'') for item in fields.get("skills", "").strip("[]").split(",") if item.strip()}
        if declared_skills != AGENT_SKILLS.get(name):
            errors.append(f"{path.relative_to(root)}: skill preload set does not match the approved noninteractive set")
        if "always return structured json matching `schemas/review.schema.json`" not in body.lower() and "return only json matching `schemas/review.schema.json`" not in body.lower():
            errors.append(f"{path.relative_to(root)}: structured report is not unconditional")

    skill_dir = root / "plugins/launchpad/skills"
    actual_skills = {path.parent.name for path in skill_dir.glob("*/SKILL.md")}
    if actual_skills != SKILLS:
        errors.append(f"skill roster must be {sorted(SKILLS)}, got {sorted(actual_skills)}")
    descriptions = {}
    for name in sorted(actual_skills):
        path = skill_dir / name / "SKILL.md"
        try:
            fields, body = frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
            continue
        description = fields.get("description", "")
        descriptions[name] = description
        if name in OPERATIONAL_SKILLS:
            for field in sorted(fields.keys() - {"name", "description"}):
                errors.append(f"{path.relative_to(root)}: unsupported frontmatter field: {field}")
        if fields.get("name") != name:
            errors.append(f"{path.relative_to(root)}: frontmatter name must be {name}")
        if "Use when" not in description or "Do not use" not in description:
            errors.append(f"{path.relative_to(root)}: description needs narrow Use when/Do not use triggers")
        if "## Evidence sources" not in body or "## Trigger boundary" not in body:
            errors.append(f"{path.relative_to(root)}: missing evidence or trigger section")

    try:
        cases = json.loads((root / "tests/fixtures/skill-triggers.json").read_text())
        for case in cases:
            if classify_skill(case["prompt"], descriptions) != case["expected"]:
                errors.append(f"skill trigger mismatch: {case['prompt']}")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        errors.append(f"skill trigger fixtures invalid: {exc}")

    try:
        cases = json.loads((root / "tests/fixtures/specialist-triggers.json").read_text())
        for case in cases:
            event, conditions = case["event"], case["conditions"]
            selected = classify_specialists(event, conditions, agent_descriptions, trusted=case.get("trusted", True))
            if selected != set(case["expected"]):
                errors.append(f"specialist trigger mismatch: {event}, {conditions}: got {sorted(selected)}")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        errors.append(f"specialist trigger fixtures invalid: {exc}")

    try:
        lock = json.loads((root / "adopted-plugins.lock.json").read_text())
        documentation = (root / "ADOPTED_PLUGINS.md").read_text()
        sources = lock.get("sources", [])
        repositories = [source.get("repository") for source in sources]
        if set(repositories) != set(EXPECTED_COMPONENTS) or len(repositories) != len(set(repositories)):
            errors.append("provenance lock must contain exactly the reviewed repositories once")
        for source in sources:
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
            component_mapping = {component.get("name"): component.get("path") for component in source.get("components", [])}
            if component_mapping != EXPECTED_COMPONENTS.get(repository):
                errors.append(f"{repository}: adopted component mapping does not match the reviewed set")
            for component in source.get("components", []):
                if not component.get("name") or not component.get("path"):
                    errors.append(f"{repository}: component missing name or path")
        marketplace = json.loads((root / ".claude-plugin/marketplace.json").read_text())
        external_entries = [entry for entry in marketplace["plugins"] if entry["name"] != "launchpad"]
        entries = {entry["name"]: entry for entry in external_entries}
        launchpad_entry = next((entry for entry in marketplace["plugins"] if entry["name"] == "launchpad"), {})
        expected_names = {name for mapping in EXPECTED_COMPONENTS.values() for name in mapping}
        if set(entries) != expected_names or len(external_entries) != len(entries):
            errors.append("pinned marketplace entries do not match the adopted component set")
        if set(launchpad_entry.get("dependencies", [])) != expected_names:
            errors.append("launchpad dependencies do not match the pinned adopted component set")
        for source in sources:
            repository, commit = source["repository"], source["commit"]
            for component in source["components"]:
                entry = entries.get(component["name"], {})
                plugin_source = entry.get("source", {})
                if repository in {"obra/superpowers", "anthropics/skills"}:
                    valid = plugin_source == {"source": "github", "repo": repository, "sha": commit}
                else:
                    valid = plugin_source == {"source": "git-subdir", "url": repository, "path": component["path"], "sha": commit}
                if not valid:
                    errors.append(f"{component['name']}: marketplace source does not consume its reviewed SHA and path")
                if repository == "anthropics/skills" and entry.get("skills") != ["./skills/webapp-testing"]:
                    errors.append("webapp-testing: marketplace entry does not expose only the reviewed skill")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
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
