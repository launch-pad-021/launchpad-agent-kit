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

    def test_skill_trigger_and_non_trigger_cases(self):
        cases = json.loads((ROOT / "tests/fixtures/skill-triggers.json").read_text())
        for case in cases:
            with self.subTest(prompt=case["prompt"]):
                self.assertEqual(classify_skill(case["prompt"]), case["expected"])

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


if __name__ == "__main__":
    unittest.main()
