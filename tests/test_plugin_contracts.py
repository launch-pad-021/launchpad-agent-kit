import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_plugin import classify_skill, classify_specialists, frontmatter, validate


ROOT = Path(__file__).resolve().parents[1]


class PluginContractTest(unittest.TestCase):
    def test_repository_contracts_are_valid(self):
        self.assertEqual(validate(ROOT), [])

    def test_skill_trigger_and_non_trigger_cases_use_production_descriptions(self):
        cases = json.loads((ROOT / "tests/fixtures/skill-triggers.json").read_text())
        descriptions = {}
        for path in (ROOT / "plugins/launchpad/skills").glob("*/SKILL.md"):
            descriptions[path.parent.name] = frontmatter(path)[0]["description"]
        for case in cases:
            with self.subTest(prompt=case["prompt"]):
                self.assertEqual(classify_skill(case["prompt"], descriptions), case["expected"])

    def test_provenance_rejects_unpinned_source(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "repo"
            shutil.copytree(ROOT, copy_root)
            lock_path = copy_root / "adopted-plugins.lock.json"
            lock = json.loads(lock_path.read_text())
            lock["sources"][0]["commit"] = "main"
            lock_path.write_text(json.dumps(lock))
            self.assertTrue(any("40-character commit SHA" in error for error in validate(copy_root)))

    def test_provenance_rejects_undocumented_source(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "repo"
            shutil.copytree(ROOT, copy_root)
            doc = copy_root / "ADOPTED_PLUGINS.md"
            doc.write_text(doc.read_text().replace("obra/superpowers", "removed/source"))
            self.assertTrue(any("missing from ADOPTED_PLUGINS.md" in error for error in validate(copy_root)))

    def test_provenance_rejects_sha_missing_from_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "repo"
            shutil.copytree(ROOT, copy_root)
            lock = json.loads((copy_root / "adopted-plugins.lock.json").read_text())
            commit = lock["sources"][0]["commit"]
            doc = copy_root / "ADOPTED_PLUGINS.md"
            doc.write_text(doc.read_text().replace(commit, "0" * 40))
            self.assertTrue(any("pinned SHA missing" in error for error in validate(copy_root)))

    def test_provenance_rejects_duplicate_source_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "repo"
            shutil.copytree(ROOT, copy_root)
            lock_path = copy_root / "adopted-plugins.lock.json"
            lock = json.loads(lock_path.read_text())
            lock["sources"][3] = copy.deepcopy(lock["sources"][0])
            lock_path.write_text(json.dumps(lock))
            self.assertTrue(any("exactly the reviewed repositories" in error for error in validate(copy_root)))

    def test_provenance_rejects_wrong_component_path(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "repo"
            shutil.copytree(ROOT, copy_root)
            lock_path = copy_root / "adopted-plugins.lock.json"
            lock = json.loads(lock_path.read_text())
            lock["sources"][1]["components"][0]["path"] = "totally/wrong/path"
            lock_path.write_text(json.dumps(lock))
            self.assertTrue(any("component mapping" in error for error in validate(copy_root)))

    def test_headless_agent_rejects_interactive_skill_preload(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "repo"
            shutil.copytree(ROOT, copy_root)
            planner = copy_root / "plugins/launchpad/agents/planner.md"
            planner.write_text(planner.read_text().replace("superpowers:writing-plans", "superpowers:brainstorming"))
            self.assertTrue(any("approved noninteractive set" in error for error in validate(copy_root)))


class SpecialistContractTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name) / "repo"
        shutil.copytree(ROOT, self.repo)
        self.plugin = self.repo / "plugins/launchpad"

    def mutate_header(self, path, key, replacement):
        lines = path.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                lines[i] = replacement
                break
        path.write_text("".join(lines))

    def test_specialist_trigger_and_non_trigger_cases(self):
        cases = json.loads((ROOT / "tests/fixtures/specialist-triggers.json").read_text())
        descriptions = {
            path.stem: frontmatter(path)[0]["description"]
            for path in (self.plugin / "agents").glob("*.md")
        }
        for case in cases:
            with self.subTest(event=case["event"], conditions=case["conditions"]):
                self.assertEqual(
                    classify_specialists(
                        case["event"], case["conditions"], descriptions, trusted=case.get("trusted", True)
                    ),
                    set(case["expected"]),
                )

    def test_rejects_misnamed_specialist_and_missing_report_contract(self):
        path = self.plugin / "agents/architecture-reviewer.md"
        self.assertTrue(path.is_file(), "missing architecture-reviewer")
        self.mutate_header(path, "name", "name: security-auditor\n")
        path.write_text(path.read_text().replace("schemas/review.schema.json", "report.json"))
        errors = validate(self.repo)
        self.assertTrue(any("frontmatter name must be architecture-reviewer" in error for error in errors))
        self.assertTrue(any("missing report schema reference" in error for error in errors))

    def test_read_only_roles_reject_write_shell_and_delegation_tools(self):
        for role in (
            "security-auditor", "architecture-reviewer", "database-reviewer", "product-design-reviewer",
            "documentation-auditor", "dependency-supply-chain-auditor", "performance-investigator",
            "debugging-investigator", "technical-researcher",
        ):
            path = self.plugin / f"agents/{role}.md"
            self.assertTrue(path.is_file(), f"missing {role}")
            original = path.read_text()
            tools = frontmatter(path)[0]["tools"]
            for forbidden in ("Write", "Bash(git push:*)", "Agent", "mcp__github__*"):
                with self.subTest(role=role, tool=forbidden):
                    path.write_text(original)
                    self.mutate_header(path, "tools", f"tools: {tools}, {forbidden}\n")
                    self.assertTrue(any(role in error and "read-only tools" in error for error in validate(self.repo)))
            path.write_text(original)

    def test_read_only_roles_reject_memory_that_implicitly_adds_write_access(self):
        path = self.plugin / "agents/security-auditor.md"
        self.assertTrue(path.is_file(), "missing security-auditor")
        path.write_text(path.read_text().replace("model: opus", "model: opus\nmemory: project"))
        self.assertTrue(any("unsupported frontmatter field: memory" in error for error in validate(self.repo)))

    def test_release_and_incident_roles_cannot_apply_operations(self):
        for role in ("release-manager", "incident-responder"):
            with self.subTest(role=role):
                path = self.plugin / f"agents/{role}.md"
                self.assertTrue(path.is_file(), f"missing {role}")
                self.mutate_header(path, "tools", "tools: Read, Bash(gh pr merge:*), Edit\n")
                self.assertTrue(any(role in error and "read-only tools" in error for error in validate(self.repo)))

    def test_test_engineer_cannot_expand_tools_beyond_test_file_edits(self):
        path = self.plugin / "agents/test-engineer.md"
        self.assertTrue(path.is_file(), "missing test-engineer")
        self.mutate_header(path, "tools", "tools: Read, Edit, Write, Bash(git push:*)\n")
        self.assertTrue(any("test-engineer" in error and "tool allowlist" in error for error in validate(self.repo)))

    def test_operational_skills_cannot_grant_extra_tools(self):
        for skill in ("release-and-deploy", "incident-response"):
            with self.subTest(skill=skill):
                path = self.plugin / f"skills/{skill}/SKILL.md"
                self.assertTrue(path.is_file(), f"missing {skill}")
                path.write_text(path.read_text().replace(f"name: {skill}", f"name: {skill}\nallowed-tools: Bash"))
                self.assertTrue(any(skill in error and "unsupported frontmatter field: allowed-tools" in error for error in validate(self.repo)))

    def test_specialist_rejects_interactive_preload(self):
        path = self.plugin / "agents/debugging-investigator.md"
        self.assertTrue(path.is_file(), "missing debugging-investigator")
        self.mutate_header(path, "skills", 'skills: ["superpowers:brainstorming"]\n')
        self.assertTrue(any("debugging-investigator" in error and "approved noninteractive set" in error for error in validate(self.repo)))

    def test_report_schema_preserves_specification_fields(self):
        schema = json.loads((ROOT / "schemas/review.schema.json").read_text())
        properties = schema["properties"]
        self.assertEqual(set(schema["required"]), {"verdict", "risk", "findings", "checks_performed", "not_inspected"})
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(properties["verdict"]["enum"], ["approve", "request_changes", "needs_human"])
        self.assertEqual(properties["risk"]["enum"], ["low", "medium", "high"])
        self.assertEqual(properties["findings"]["type"], "array")
        finding = properties["findings"]["items"]
        self.assertEqual(
            set(finding["required"]),
            {"severity", "file", "line", "evidence", "trigger", "impact", "fix", "test", "confidence"},
        )
        self.assertFalse(finding["additionalProperties"])
        self.assertEqual(finding["properties"]["severity"]["enum"], ["critical", "high", "medium", "low", "nit"])
        self.assertEqual(finding["properties"]["confidence"]["enum"], ["confirmed", "likely", "possible"])
        self.assertEqual(finding["properties"]["line"], {"type": "integer", "minimum": 1})
        for field in ("checks_performed", "not_inspected"):
            self.assertEqual(properties[field], {"type": "array", "items": {"type": "string"}})


if __name__ == "__main__":
    unittest.main()
