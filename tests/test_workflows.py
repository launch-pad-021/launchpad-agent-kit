import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TEMPLATES = ROOT / "templates"


class WorkflowContractTest(unittest.TestCase):
    def test_required_reusable_workflows_exist_with_safety_controls(self):
        for name in ("agent-implement.yml", "agent-review.yml", "ci-fix.yml", "release.yml"):
            text = (WORKFLOWS / name).read_text()
            with self.subTest(name=name):
                self.assertIn("workflow_call:", text)
                self.assertIn("permissions:", text)
                self.assertIn("concurrency:", text)
                self.assertIn("timeout-minutes:", text)
                self.assertIn("AGENTS_ENABLED", text)
                self.assertNotIn("pull_request_target", text)
                self.assertNotRegex(text, r"permissions:\s*(write-all|read-all)")

    def test_external_actions_are_pinned_to_full_shas(self):
        action = re.compile(r"uses:\s*([^./\s][^@\s]*)@([^\s#]+)")
        for path in [*WORKFLOWS.glob("*.yml"), *TEMPLATES.glob("ci-*.yml")]:
            for repository, ref in action.findall(path.read_text()):
                with self.subTest(path=path.name, repository=repository):
                    self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_templates_expose_stable_checks_and_required_commands(self):
        requirements = {
            "ci-go.yml": ("gofmt", "golangci-lint", "go vet", "go test -race ./...", "govulncheck"),
            "ci-rust.yml": ("cargo fmt --check", "cargo clippy", "cargo test", "cargo deny check"),
            "ci-python.yml": ("ruff check", "ruff format --check", "pyright", "pytest", "pip-audit"),
            "ci-node.yml": ("eslint", "tsc --noEmit", "vitest", "npm audit --omit=dev"),
            "ci-next.yml": ("eslint", "tsc --noEmit", "vitest", "playwright", "axe", "375", "768", "1280"),
        }
        for filename, commands in requirements.items():
            text = (TEMPLATES / filename).read_text()
            with self.subTest(filename=filename):
                self.assertIn("workflow_call:", text)
                self.assertEqual(text, (WORKFLOWS / filename).read_text())
                for check in ("CI / build", "CI / lint", "CI / types", "CI / tests", "CI / security", "CI / contracts"):
                    self.assertIn(check, text)
                for command in commands:
                    self.assertIn(command, text)

    def test_workflows_set_bounded_role_contracts(self):
        implement = (WORKFLOWS / "agent-implement.yml").read_text()
        review = (WORKFLOWS / "agent-review.yml").read_text()
        fixer = (WORKFLOWS / "ci-fix.yml").read_text()
        self.assertIn("LP_AGENT_ROLE: implementer", implement)
        self.assertIn("LP_ISSUE_NUMBER:", implement)
        self.assertIn("max_attempts", implement)
        self.assertIn("max_budget_usd", implement)
        self.assertIn("LP_AGENT_ROLE: ${{ matrix.reviewer }}", review)
        self.assertIn("max_review_rounds", review)
        self.assertIn("LP_AGENT_ROLE: ci-fixer", fixer)
        self.assertIn("max_attempts", fixer)


class DecisionHelperTest(unittest.TestCase):
    def run_helper(self, name, evidence):
        proc = subprocess.run(
            ["python3", str(ROOT / "scripts" / name)],
            input=json.dumps(evidence), text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_reviewer_fixtures(self):
        cases = json.loads((ROOT / "tests/fixtures/reviewer-cases.json").read_text())
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(self.run_helper("select_reviewers.py", case["evidence"]), case["expected"])

    def test_merge_gate_fixtures(self):
        cases = json.loads((ROOT / "tests/fixtures/merge-gate-cases.json").read_text())
        for case in cases:
            with self.subTest(case=case["name"]):
                result = self.run_helper("merge_gate.py", case["evidence"])
                self.assertEqual(result["allowed"], case["allowed"])
                self.assertEqual(result["status"], "merge-gate")
                self.assertIsInstance(result["reasons"], list)


if __name__ == "__main__":
    unittest.main()
