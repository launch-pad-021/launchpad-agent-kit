.PHONY: validate test

validate:
	python3 -c 'import json, pathlib; [json.loads(p.read_text()) for p in pathlib.Path(".").rglob("*.json")]'
	bash -n plugins/launchpad/hooks/scripts/*.sh
	test -f .claude-plugin/marketplace.json
	test -f plugins/launchpad/.claude-plugin/plugin.json
	test -f schemas/review.schema.json

test:
	uv run --no-project --with pytest pytest -q scripts/test_risk.py
