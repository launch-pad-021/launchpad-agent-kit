import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RISK_TEST = ROOT / "scripts/test-risk.sh"


class RiskTestRunnerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.bin = self.temp / "bin"
        self.bin.mkdir()
        self.log = self.temp / "calls.log"

    def write_uv(self, offline_exit):
        uv = self.bin / "uv"
        uv.write_text(f"""#!/bin/sh
printf '%s\\n' "${{UV_OFFLINE:-0}}" >> "$CALL_LOG"
if [ "${{UV_OFFLINE:-0}}" = 1 ]; then exit {offline_exit}; fi
printf '16 passed in 0.01s\\n'
""")
        uv.chmod(0o755)

    def invoke(self):
        return subprocess.run(
            [RISK_TEST], cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin", "CALL_LOG": str(self.log)},
        )

    def test_cache_miss_falls_back_to_online_resolution(self):
        self.write_uv(2)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["1", "0"])

    def test_real_test_failure_does_not_retry_online(self):
        self.write_uv(1)
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.log.read_text().splitlines(), ["1"])


if __name__ == "__main__":
    unittest.main()
