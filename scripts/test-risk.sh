#!/usr/bin/env bash
set -uo pipefail

command=(uv run --no-project --no-python-downloads --python python3 --with pytest pytest -q scripts/test_risk.py)
UV_OFFLINE=1 "${command[@]}"
status=$?
if [ "$status" -eq 0 ]; then
  exit 0
fi
if [ "$status" -ne 2 ]; then
  exit "$status"
fi
exec "${command[@]}"
