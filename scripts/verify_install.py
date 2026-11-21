#!/usr/bin/env python3
"""Assert an isolated Claude install resolved every adopted plugin to its lock SHA."""

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not config_dir:
        raise RuntimeError("CLAUDE_CONFIG_DIR must point to the isolated install")
    installed_path = Path(config_dir) / "plugins/installed_plugins.json"
    installed = json.loads(installed_path.read_text()).get("plugins", {})
    lock = json.loads((ROOT / "adopted-plugins.lock.json").read_text())
    expected = {
        component["name"]: source["commit"]
        for source in lock["sources"]
        for component in source["components"]
    }
    expected_ids = {f"{name}@launchpad-agent-kit" for name in expected} | {"launchpad@launchpad-agent-kit"}
    if set(installed) != expected_ids:
        raise RuntimeError("installed plugin set does not exactly match Launchpad and its pinned dependencies")
    for name, commit in expected.items():
        records = installed.get(f"{name}@launchpad-agent-kit", [])
        if len(records) != 1 or records[0].get("gitCommitSha") != commit:
            raise RuntimeError(f"{name}: installed commit does not match {commit}")
    launchpad = installed.get("launchpad@launchpad-agent-kit", [])
    if len(launchpad) != 1:
        raise RuntimeError("launchpad plugin is not installed exactly once")
    print(f"verified launchpad plus {len(expected)} pinned dependencies")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
