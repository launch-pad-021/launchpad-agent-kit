#!/usr/bin/env python3
"""Evaluate the deterministic §11.3 merge gate from trusted current-head evidence."""
from __future__ import annotations

import json
import sys


REQUIRED_CI = (
    "CI / build", "CI / lint", "CI / types", "CI / tests", "CI / security", "CI / contracts"
)


def evaluate(source: object) -> dict:
    reasons: list[str] = []
    if not isinstance(source, dict):
        return {"allowed": False, "status": "merge-gate", "reasons": ["evidence is missing or malformed"]}
    if source.get("agents_enabled") is not True:
        reasons.append("agents are disabled")
    if source.get("hold") is not False:
        reasons.append("PR is held or hold evidence is missing")
    if source.get("head_matches") is not True:
        reasons.append("evidence is stale for the current head")
    if source.get("up_to_date") is not True:
        reasons.append("branch is not up to date with main")
    if source.get("unresolved_threads") != 0:
        reasons.append("review threads are unresolved or unknown")
    risk = source.get("risk")
    if risk not in {"low", "medium", "high"}:
        reasons.append("risk result is missing or invalid")
    elif risk == "high" and source.get("developer_approved") is not True:
        reasons.append("high-risk change lacks developer approval")
    if source.get("agent_config") is not False:
        reasons.append("agent-config changes are developer-merge-only")
    ci = source.get("ci")
    if not isinstance(ci, dict):
        reasons.append("CI evidence is missing")
    else:
        for check in REQUIRED_CI:
            if ci.get(check) != "success":
                reasons.append(f"{check} is not successful")
    selected = source.get("selected_reviewers")
    reviews = source.get("reviews")
    if not isinstance(selected, list) or not selected or not isinstance(reviews, dict):
        reasons.append("review evidence is missing")
    else:
        for reviewer in selected:
            if not isinstance(reviewer, str) or reviews.get(reviewer) != "approve":
                reasons.append(f"reviewer {reviewer!r} has not approved")
    return {"allowed": not reasons, "status": "merge-gate", "reasons": reasons}


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        payload = None
    json.dump(evaluate(payload), sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
