#!/usr/bin/env python3
"""Select Launchpad reviewers from trusted, machine-generated PR evidence."""
from __future__ import annotations

import json
import re
import sys


ORDER = (
    "code-reviewer",
    "correctness-verifier",
    "security-auditor",
    "architecture-reviewer",
    "database-reviewer",
    "product-design-reviewer",
    "documentation-auditor",
    "dependency-supply-chain-auditor",
)


def select(evidence: object) -> list[str]:
    if not isinstance(evidence, dict) or not isinstance(evidence.get("files"), list):
        return list(ORDER)  # incomplete evidence fails closed to every specialist
    files = evidence["files"]
    if not files or any(not isinstance(path, str) or not path for path in files):
        return list(ORDER)
    joined = "\n".join(files).lower()
    chosen = set(ORDER[:2])
    if evidence.get("risk") == "high" or evidence.get("new_endpoint") or re.search(
        r"(^|[/_.-])(auth|csrf|secret|token|webhook|middleware|input)([/_.-]|$)", joined
    ):
        chosen.add("security-auditor")
    if evidence.get("new_dependency") or re.search(r"(^|/)(proto|events|contracts?)/|(^|/)(go\.mod|cargo\.toml|package\.json|pyproject\.toml)$", joined, re.M):
        chosen.add("architecture-reviewer")
    if re.search(r"(^|/)(migrations?|sql|clickhouse)(/|\.|$)|\.sql$", joined, re.M):
        chosen.add("database-reviewer")
    if re.search(r"(^|/)(dashboard|app|pages?)/.*\.(tsx|jsx|css|scss)$", joined, re.M):
        chosen.add("product-design-reviewer")
    if evidence.get("api_or_behavior") or re.search(r"(^|/)(api|config)(/|\.|$)", joined, re.M):
        chosen.add("documentation-auditor")
    if evidence.get("dependency_pr") or evidence.get("new_dependency"):
        chosen.add("dependency-supply-chain-auditor")
    return [reviewer for reviewer in ORDER if reviewer in chosen]


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        payload = None
    json.dump(select(payload), sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
