import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_plugin import classify_skill, validate


ROOT = Path(__file__).resolve().parents[1]


class PluginContractTest(unittest.TestCase):
    def test_repository_contracts_are_valid(self):
        self.assertEqual(validate(ROOT), [])

    def test_skill_trigger_and_non_trigger_cases_use_production_descriptions(self):
        cases = json.loads((ROOT / "tests/fixtures/skill-triggers.json").read_text())
        descriptions = {}
        for path in (ROOT / "plugins/launchpad/skills").glob("*/SKILL.md"):
            header = path.read_text().split("---", 2)[1]
            descriptions[path.parent.name] = next(
                line.split(":", 1)[1].strip() for line in header.splitlines() if line.startswith("description:")
            )
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


if __name__ == "__main__":
    unittest.main()
