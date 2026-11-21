#!/usr/bin/env python3
"""Classify trusted PR evidence under Launchpad's deterministic risk rules (§11.1)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


LEVELS = {"low": 0, "medium": 1, "high": 2}
REPORT_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "risk.schema.json"

EVIDENCE_FIELDS = {"repo", "files", "diff", "labels", "dependencies", "contracts", "migrations"}
DIFF_FLAGS = {
    "new_service_call": ("medium", "new service-to-service call"),
    "new_event": ("medium", "new event"),
    "security_sensitive": ("high", "diff touches a security-sensitive area"),
}
DEPENDENCY_CHANGES = {"new", "major", "minor", "patch", "removed", "unknown"}
CONTRACT_RESULTS = {"none", "additive", "breaking", "unknown"}
MIGRATION_RESULTS = {"non_destructive", "destructive", "unknown"}

AGENT_CONFIG_REPOS = {"launchpad-agent-kit", "launchpad-meta"}
AGENT_CONFIG_PATH = re.compile(
    r"^(?:\.github|\.claude|\.claude-plugin|plugins/launchpad)(?:/|\Z)"
    r"|(?:^|/)(?:CODEOWNERS|CLAUDE\.md|AGENTS\.md)\Z"
    r"|^renovate\.json\Z"
)
TEST_DOC_PATH = re.compile(
    r"(?:^|/)tests?/"
    r"|(?:_test\.go|\.test\.[cm]?[jt]sx?|\.spec\.[cm]?[jt]sx?|\.md)\Z"
    r"|(?:^|/)test_[^/]*\.py\Z|^docs/"
)
MIGRATION_PATH = re.compile(r"(?:^|/)migrations/")
CONTRACT_PATH = re.compile(r"^(?:proto|events)/")
DEP_MANIFESTS = re.compile(r"(?:^|/)(?:go\.mod|Cargo\.toml|package\.json|pyproject\.toml)\Z")

HIGH_RISK_PATHS = {
    "launchpad-identity": (r"", "identity: auth, sessions, tokens, JWT"),
    "launchpad-projects": (
        r"^internal/(?:crypto|encryption|secrets|envvars|runtimeenv)/"
        r"|(?:^|/)get_?runtime_?env\.[^/]+\Z",
        "projects: secret handling / GetRuntimeEnv",
    ),
    "launchpad-scm": (r"^src/webhooks?(?:/|\.)", "scm: webhook signature verification"),
    "launchpad-router": (r"", "router: Traefik rendering and hostname validation"),
    "launchpad-runtime-agent": (r"", "runtime-agent: Docker socket and container security"),
    "launchpad-builder": (r"", "builder: BuildKit sandbox and registry"),
    "launchpad-gateway": (
        r"^internal/(?:middleware/)?(?:auth|csrf|rate[-_]?limit)(?:/|\.)",
        "gateway: auth/CSRF/rate limiting",
    ),
    "launchpad-ingest": (
        r"^src/(?:handlers?|validate|validation|input)(?:/|\.|_)",
        "ingest: untrusted input handling",
    ),
    "launchpad-analytics": (
        r"^src/lp_analytics/(?:ask|chusers|clickhouse_users)(?:/|\.|_)",
        "analytics: Ask / ClickHouse user management",
    ),
}

SHARED_HIGH_RISK_PATHS = (
    (
        r"(?:^|/)traefik(?:[-_.]static)?\.(?:ya?ml|toml)\Z|(?:^|/)traefik/static/",
        "Traefik static configuration",
    ),
    (
        r"(?:^|/)clickhouse/(?:[^/]+/)*(?:users|settings[-_]profiles?|row[-_]polic(?:y|ies))(?:[./]|\Z)",
        "ClickHouse users, settings profiles, or row policies",
    ),
)
DESTRUCTIVE_SQL = re.compile(
    r"\b(?:DROP\s+(?:TABLE|COLUMN|INDEX|TYPE|DATABASE)|RENAME\s+(?:COLUMN|TO)"
    r"|ALTER\s+COLUMN\s+\S+\s+(?:TYPE|SET\s+NOT\s+NULL)|TRUNCATE)\b",
    re.IGNORECASE,
)


class EvidenceError(ValueError):
    """Required PR evidence is missing, malformed, or ambiguous."""


class RiskReport:
    def __init__(self):
        self.agent_config = False
        self.findings: set[tuple[str, str]] = set()

    def add(self, level: str, reason: str):
        self.findings.add((level, reason))

    def as_json_object(self) -> dict:
        ordered = sorted(self.findings, key=lambda finding: (-LEVELS[finding[0]], finding[1]))
        if not ordered:
            ordered = [("low", "no risk rules matched")]
        level = ordered[0][0]
        return {
            "level": level,
            "status": f"risk/{level}",
            "agent_config": self.agent_config,
            "reasons": [f"{severity}: {reason}" for severity, reason in ordered],
        }


def valid_repo(repo: object) -> bool:
    return isinstance(repo, str) and re.fullmatch(r"launchpad-[a-z0-9]+(?:-[a-z0-9]+)*", repo) is not None


def valid_path(path: object) -> bool:
    return (
        isinstance(path, str)
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and not re.search(r"[\x00\ud800-\udfff]", path)
    )


def apply_path_rules(report: RiskReport, repo: str, files: list[str], labels: list[str]):
    if repo in AGENT_CONFIG_REPOS:
        report.agent_config = True
        report.add("high", f"{repo} is agent configuration")
    if "agent-config" in labels:
        report.agent_config = True
        report.add("high", "label agent-config")
    for path in files:
        if AGENT_CONFIG_PATH.search(path):
            report.agent_config = True
            report.add("high", f"agent-config path {json.dumps(path)}")

    non_test = [path for path in files if not TEST_DOC_PATH.search(path)]
    for pattern, reason in SHARED_HIGH_RISK_PATHS:
        if any(re.search(pattern, path, re.IGNORECASE) for path in non_test):
            report.add("high", reason)
    if repo in HIGH_RISK_PATHS:
        pattern, reason = HIGH_RISK_PATHS[repo]
        if any(re.search(pattern, path, re.IGNORECASE) for path in non_test):
            report.add("high", reason)

    if repo == "launchpad-infra":
        if any(path != "versions.env" for path in files):
            report.add("high", "infra change other than versions.env")
        if "inherit:high" in labels:
            report.add("high", "release contains a high-risk change")
        if "inherit:medium" in labels or "has-migration" in labels:
            report.add("medium", "release contains a migration or medium-risk change")
    for level in LEVELS:
        label = f"risk:{level}"
        if label in labels:
            report.add(level, f"label {label}")


def apply_diff_rules(report: RiskReport, diff: object):
    if not isinstance(diff, dict) or diff.keys() != {"changed_lines", *DIFF_FLAGS}:
        report.add("high", "diff metadata is incomplete or malformed")
        return
    changed_lines = diff["changed_lines"]
    if type(changed_lines) is not int or changed_lines < 0:
        report.add("high", "diff line count must be a nonnegative integer")
    elif changed_lines > 400:
        report.add("medium", "large change (more than 400 lines)")
    for flag, (level, reason) in DIFF_FLAGS.items():
        if type(diff[flag]) is not bool:
            report.add("high", f"diff assessment {flag} is unavailable")
        elif diff[flag]:
            report.add(level, reason)


def apply_dependency_rules(report: RiskReport, dependencies: object):
    if not isinstance(dependencies, list):
        report.add("high", "dependency assessment must be a list")
        return
    names = set()
    for entry in dependencies:
        if not isinstance(entry, dict) or entry.keys() != {"name", "change"}:
            report.add("high", "dependency assessment entry is malformed")
            continue
        name, change = entry["name"], entry["change"]
        if (
            not isinstance(name, str) or not name.strip()
            or not isinstance(change, str) or change not in DEPENDENCY_CHANGES
        ):
            report.add("high", "dependency assessment entry is invalid")
            continue
        if name in names:
            report.add("high", "dependency assessment entry is duplicated")
        names.add(name)
        if change == "unknown":
            report.add("high", "dependency assessment is unknown")
        elif change == "new":
            report.add("medium", "new dependency")
        elif change == "major":
            report.add("medium", "major-version dependency update")


def apply_contract_rules(report: RiskReport, repo: str, files: list[str], result: object):
    if not isinstance(result, str) or result not in CONTRACT_RESULTS:
        report.add("high", "contract assessment is malformed")
    elif result == "breaking":
        report.add("high", "breaking contract change")
    elif result == "additive":
        report.add("medium", "additive contract change")
    elif result == "unknown" or (
        result == "none"
        and repo == "launchpad-contracts"
        and any(CONTRACT_PATH.search(path) and not TEST_DOC_PATH.search(path) for path in files)
    ):
        report.add("high", "changed contracts lack a conclusive compatibility result")


def apply_migration_rules(report: RiskReport, files: list[str], migrations: object):
    if not isinstance(migrations, dict):
        report.add("high", "migration assessment must map changed paths to results")
        return
    changed_paths = set(files)
    missing = {
        path for path in changed_paths
        if MIGRATION_PATH.search(path) and not TEST_DOC_PATH.search(path)
    } - migrations.keys()
    if missing:
        report.add("high", "changed migrations lack a classification")
    for path, result in migrations.items():
        if not valid_path(path) or path not in changed_paths or not isinstance(result, str) or result not in MIGRATION_RESULTS:
            report.add("high", "migration assessment entry is invalid or does not match a changed path")
            continue
        quoted_path = json.dumps(path)
        if result == "destructive":
            report.add("high", f"destructive migration in {quoted_path}")
        elif result == "non_destructive":
            report.add("medium", f"non-destructive migration in {quoted_path}")
        else:
            report.add("high", f"unknown migration classification in {quoted_path}")


def classify_evidence(source: object) -> dict:
    """Classify the structured, machine-generated evidence used by CI."""
    report = RiskReport()
    if not isinstance(source, dict):
        report.add("high", "PR evidence must be a JSON object")
        return report.as_json_object()

    repo = source.get("repo")
    files = source.get("files")
    labels = source.get("labels")
    valid_files = [path for path in files if valid_path(path)] if isinstance(files, list) else []
    valid_labels = [label for label in labels if isinstance(label, str) and label] if isinstance(labels, list) else []
    apply_path_rules(report, repo if valid_repo(repo) else "", valid_files, valid_labels)

    if source.keys() != EVIDENCE_FIELDS:
        report.add("high", "PR evidence fields are missing or unexpected")
    if not valid_repo(repo):
        report.add("high", "repository name is missing or invalid")
    if not valid_files or len(valid_files) != len(files):
        report.add("high", "changed paths are missing or invalid")
    if not isinstance(labels, list) or len(valid_labels) != len(labels):
        report.add("high", "labels must be an array of nonempty strings")

    apply_diff_rules(report, source.get("diff"))
    apply_dependency_rules(report, source.get("dependencies"))
    apply_contract_rules(report, repo, valid_files, source.get("contracts"))
    apply_migration_rules(report, valid_files, source.get("migrations"))
    return report.as_json_object()


def added_lines_by_file(diff: str) -> dict[str, list[str]]:
    """Read the starter patch format for local callers of classify()."""
    added: dict[str, list[str]] = {}
    current = None
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            current = line.removeprefix("+++ ").removeprefix("b/")
            added.setdefault(current, [])
        elif current and line.startswith("+"):
            added[current].append(line[1:])
    return added


def changed_line_count(diff: str) -> int:
    return sum(
        line.startswith(("+", "-")) and not line.startswith(("+++ ", "--- "))
        for line in diff.split("\n")
    )


def classify(
    repo: str,
    files: list[str],
    diff: str = "",
    labels: list[str] | None = None,
    buf_breaking: bool = False,
) -> dict:
    """Preserve the starter Python API for local classification of partial evidence."""
    report = RiskReport()
    apply_path_rules(report, repo, files, labels or [])
    if repo == "launchpad-contracts":
        if buf_breaking:
            report.add("high", "breaking contract change (buf breaking failed)")
        elif any(CONTRACT_PATH.search(path) for path in files):
            report.add("medium", "additive contract change")

    for path, lines in added_lines_by_file(diff).items():
        if MIGRATION_PATH.search(path):
            level, reason = ("high", "destructive migration in") if DESTRUCTIVE_SQL.search("\n".join(lines)) else (
                "medium", "migration",
            )
            report.add(level, f"{reason} {json.dumps(path)}")
    if any(DEP_MANIFESTS.search(path) for path in files):
        report.add("medium", "dependency manifest changed")
    line_count = changed_line_count(diff)
    if line_count > 400:
        report.add("medium", f"large change ({line_count} lines)")
    return report.as_json_object()


def unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    values = {}
    for key, value in pairs:
        if key in values:
            raise EvidenceError("PR evidence contains duplicate JSON fields")
        values[key] = value
    return values


def validate_report(report: dict, schema: dict):
    """Validate the risk-report schema without adding a CI runtime dependency."""
    fields = schema["properties"]
    level = report.get("level")
    status = report.get("status")
    reasons = report.get("reasons")
    matching_statuses = {
        pair["properties"]["level"]["const"]: pair["properties"]["status"]["const"]
        for pair in schema["oneOf"]
    }
    if (
        set(report) != set(schema["required"])
        or level not in fields["level"]["enum"]
        or status not in fields["status"]["enum"]
        or status != matching_statuses.get(level)
        or type(report["agent_config"]) is not bool
        or not isinstance(reasons, list)
        or len(reasons) < fields["reasons"]["minItems"]
        or not all(isinstance(reason, str) and len(reason) >= fields["reasons"]["items"]["minLength"] for reason in reasons)
        or len(reasons) != len(set(reasons))
    ):
        raise RuntimeError("risk report does not conform to schemas/risk.schema.json")


class EvidenceArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str):
        raise EvidenceError("risk classifier arguments are missing, invalid, or mixed")


def main(argv=None):
    parser = EvidenceArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", action="append", help="trusted JSON evidence file, or - for stdin")
    parser.add_argument("--repo", help="repository name for the starter CLI")
    parser.add_argument("--files", help="paths file for the starter CLI")
    parser.add_argument("--diff", help="patch file for the starter CLI")
    parser.add_argument("--labels", help="comma-separated labels for the starter CLI")
    parser.add_argument("--buf-breaking", action="store_true", help="breaking check failed in the starter CLI")

    try:
        args = parser.parse_args(argv)
        legacy_options = (args.repo, args.files, args.diff, args.labels)
        if args.input is not None:
            if len(args.input) != 1 or any(option is not None for option in legacy_options) or args.buf_breaking:
                parser.error("")
            input_path, = args.input
            raw = sys.stdin.buffer.read() if input_path == "-" else Path(input_path).read_bytes()
            source = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_json_object)
            result = classify_evidence(source)
        else:
            # The starter CLI has no dependency, migration, or semantic diff assessments.
            # Retain positive path and label evidence while withholding low/medium statuses.
            paths = Path(args.files).read_text(encoding="utf-8") if args.files else ""
            files = [path for path in paths.split("\0" if "\0" in paths else "\n") if valid_path(path)]
            labels = (args.labels or "").split(",")
            report = RiskReport()
            apply_path_rules(report, args.repo or "", files, labels)
            report.add("high", "complete PR evidence is required via --input")
            result = report.as_json_object()
    except (OSError, ValueError, RecursionError) as error:
        report = RiskReport()
        reason = str(error) if isinstance(error, EvidenceError) else (
            "PR evidence could not be read as an unambiguous JSON document"
        )
        report.add("high", reason)
        result = report.as_json_object()

    validate_report(result, json.loads(REPORT_SCHEMA.read_text(encoding="utf-8")))
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
