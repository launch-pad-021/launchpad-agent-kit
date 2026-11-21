.PHONY: validate test verify-provenance verify-install

validate:
	python3 scripts/validate_plugin.py
	claude plugin validate . --strict
	claude plugin validate plugins/launchpad --strict
	claude --plugin-dir ./plugins/launchpad plugin details launchpad >/dev/null
	for hook in plugins/launchpad/hooks/scripts/*.sh; do /bin/sh -n "$$hook" || exit 1; done

test:
	python3 -m unittest discover -s tests -v
	scripts/test-risk.sh

verify-provenance:
	python3 scripts/verify_provenance.py

verify-install:
	python3 scripts/verify_install.py
