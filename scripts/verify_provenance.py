#!/usr/bin/env python3
"""Verify pinned commits and component paths against GitHub without executing them."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def gh(*arguments):
    result = subprocess.run(["gh", "api", *arguments], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def main():
    lock = json.loads((ROOT / "adopted-plugins.lock.json").read_text())
    for source in lock["sources"]:
        repository, commit = source["repository"], source["commit"]
        resolved = json.loads(gh(f"repos/{repository}/commits/{commit}"))["sha"]
        if resolved != commit:
            raise RuntimeError(f"{repository}: commit did not resolve exactly")
        tree = json.loads(gh(f"repos/{repository}/git/trees/{commit}?recursive=1"))["tree"]
        paths = {item["path"] for item in tree}
        for component in source["components"]:
            path = component["path"]
            if path != "." and path not in paths:
                raise RuntimeError(f"{repository}@{commit}: missing {path}")
        print(f"verified {repository}@{commit}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
