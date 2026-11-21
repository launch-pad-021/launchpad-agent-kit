"""Exercise the installed hook entry points with Claude's JSON protocol."""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "plugins/launchpad/hooks"
REPORT = {
    "verdict": "approve", "risk": "low", "findings": [],
    "checks_performed": ["Inspected the diff and ran fast checks."], "not_inspected": [],
}
EVENTS = {
    "guard-bash": "PreToolUse", "guard-paths": "PreToolUse",
    "session-start": "SessionStart", "stop-checks": "Stop",
}


class HookTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        self.repo = self.temp / "launchpad-meta"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "agent/12-hook"], cwd=self.repo, check=True)
        self.bin = self.temp / "bin"
        self.bin.mkdir()
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "HOME": str(self.temp), "CLAUDE_PROJECT_DIR": str(self.repo),
            "LP_ISSUE_NUMBER": "12", "LC_ALL": "C",
        }

    def invoke(self, hook, role="launchpad:implementer", raw=None, **fields):
        event = EVENTS[hook]
        payload = {"cwd": str(self.repo), "hook_event_name": event, **fields}
        if role is not None:
            payload["agent_type"] = role
        if hook == "guard-bash":
            payload.setdefault("tool_name", "Bash")
        if hook == "guard-paths":
            payload.setdefault("tool_name", "Write")
        if hook == "stop-checks":
            payload.setdefault("stop_hook_active", False)
        return subprocess.run(
            ["/bin/bash", str(HOOKS / "scripts" / (hook + ".sh"))],
            input=raw if raw is not None else json.dumps(payload),
            text=True, capture_output=True, cwd=self.repo, env=self.env, timeout=12,
        )

    def assert_blocked(self, result, hook):
        if hook == "stop-checks":
            self.assertEqual(result.returncode, 0)
            self.assertIn('"block"', result.stdout)
            self.assertTrue(json.loads(result.stdout)["reason"])
        elif hook == "session-start":
            self.assertEqual(result.returncode, 0)
            self.assertIn('"continue"', result.stdout)
            self.assertIs(json.loads(result.stdout)["continue"], False)
        else:
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr.strip())
        self.assertNotIn("synthetic-marker", result.stdout + result.stderr)

    def tool(self, hook, content, role="launchpad:implementer"):
        key = "command" if hook == "guard-bash" else "file_path"
        return self.invoke(hook, role, tool_input={key: content})

    def test_executable_entry_points(self):
        for hook in EVENTS:
            with self.subTest(hook=hook):
                self.assertTrue((HOOKS / "scripts" / (hook + ".sh")).stat().st_mode & stat.S_IXUSR)

    def test_manifest_events(self):
        registered = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
        self.assertTrue({"PostToolUse", "SubagentStop"} <= registered.keys())

    def test_invalid_inputs_fail_closed(self):
        for hook in EVENTS:
            for value in ("{synthetic-marker", "null", "[]", "{}", '{"cwd":"a","cwd":"b"}'):
                with self.subTest(hook=hook, value=value):
                    self.assert_blocked(self.invoke(hook, raw=value), hook)
        for role in (None, "", "unrecognized", "foreign:implementer"):
            for hook, value in (("guard-bash", "git status"), ("guard-paths", "src/safe.py")):
                with self.subTest(hook=hook, role=role):
                    self.assert_blocked(self.tool(hook, value, role), hook)

    def test_trusted_launcher_fallback(self):
        self.env["LP_AGENT_ROLE"] = "code-reviewer"
        self.assertEqual(self.tool("guard-bash", "git status", None).returncode, 0)
        self.assert_blocked(self.tool("guard-paths", "ok.txt", None), "guard-paths")
        self.assert_blocked(self.tool("guard-paths", "ok.txt"), "guard-paths")

    def test_missing_workspace(self):
        self.env.pop("CLAUDE_PROJECT_DIR")
        self.assert_blocked(self.tool("guard-bash", "git status"), "guard-bash")
        self.assert_blocked(self.tool("guard-paths", "ok.txt"), "guard-paths")

    def test_command_decisions(self):
        denied = [
            "git push --force", "git push origin main", "git reset --hard",
            "rm -rf ../outside", "docker ps", "ssh example.invalid", "aws help",
            "gh repo edit", "gh release delete old", "curl https://example.invalid",
            "wget https://example.invalid", "git -c synthetic-marker status",
            "env git status", "bash -c 'git status'", "eval true",
            "git status && echo synthetic-marker", "git status > .github/marker",
            "echo $SHELL", "echo `pwd`", "echo $(pwd)", "cat .env",
            "printenv", "git show HEAD:.env", "git status\necho synthetic-marker",
            "git status --porcelain | sh", "npm exec arbitrary", "make -f other",
            "printf synthetic-marker", "git add .github/workflows/check.yml",
        ]
        for cmd in denied:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.tool("guard-bash", cmd), "guard-bash")
        for cmd in ("git status", "git diff --stat", "git log -1", "pwd",
                    "go test ./...", "cargo test", "npm ci --ignore-scripts", "make test"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.tool("guard-bash", cmd).returncode, 0)
        self.assert_blocked(self.tool("guard-bash", "git add src/x", "code-reviewer"), "guard-bash")

    def test_role_and_path_decisions(self):
        (self.repo / ".github").mkdir()
        (self.repo / "alias").symlink_to(self.repo / ".github")
        (self.repo / "outside").symlink_to(self.temp)
        for path in (".github/workflows/ci.yml", ".claude/settings.json", ".git/config",
                     "CODEOWNERS", "docs/CODEOWNERS", "CLAUDE.md", "AGENTS.md", "renovate.json",
                     "nested/.env.local", "nested/secrets/value", "private.key", "cert.pem",
                     "src/../x", "../outside.txt", str(self.temp / "sibling"), "alias/workflows/x",
                     "outside/x", ".github/synthetic-marker", ".GiTHuB/a", ""):
            with self.subTest(path=path):
                self.assert_blocked(self.tool("guard-paths", path), "guard-paths")
        for role, path, allow in (
            ("implementer", "src/new.py", True), ("ci-fixer", str(self.repo / "src/new.go"), True),
            ("code-reviewer", "src/new.go", False), ("conductor", "README.md", False),
            ("test-engineer", "tests/test_x.py", True), ("test-engineer", "src/x_test.go", True),
            ("test-engineer", "src/x.go", False), ("planner", "src/x.py", False),
            ("release-manager", "versions.env", False), ("incident-responder", "versions.env", False),
        ):
            with self.subTest(role=role, path=path):
                self.assertEqual(self.tool("guard-paths", path, role).returncode, 0 if allow else 2)
        subprocess.run(["git", "switch", "-q", "-c", "plan/A0"], cwd=self.repo, check=True)
        self.assertEqual(self.tool("guard-paths", "plans/A0.md", "planner").returncode, 0)
        self.repo.rename(self.temp / "launchpad-infra")
        self.repo = self.temp / "launchpad-infra"
        self.env["CLAUDE_PROJECT_DIR"] = str(self.repo)
        for role in ("release-manager", "incident-responder"):
            self.assertEqual(self.tool("guard-paths", "versions.env", role).returncode, 0)
            self.assert_blocked(self.tool("guard-paths", "compose.yml", role), "guard-paths")

    def test_post_edit_formatter(self):
        (self.repo / "src").mkdir()
        target = self.repo / "src/scoped.go"
        target.write_text("package scoped\n")
        self.stub("gofmt", 'test "$1" = -w && echo formatted >> "$2"')
        result = self.invoke("guard-paths", hook_event_name="PostToolUse", tool_input={"file_path": str(target)})
        self.assertEqual(result.returncode, 0)
        self.assertIn("formatted", target.read_text())

    def stub(self, program, body):
        path = self.bin / program
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def test_session_context(self):
        self.stub("gh", """case "$1 $2" in
          'issue view') echo '{"title":"Review map","body":"Check the map"}';;
          'pr list') echo '[{"number":42}]';;
          'pr view') echo '{"comments":[{"authorAssociation":"OWNER","body":"### Handoff — run 1\nmap ready"}]}' | tr '\n' ' ';;
        esac""".replace("run 1\nmap ready", "run 1; map ready"))
        (self.repo / "src").mkdir()
        result = self.invoke("session-start")
        for item in ("12", "src", "Review map", "map ready"):
            self.assertIn(item, result.stdout)
        self.env.pop("LP_ISSUE_NUMBER")
        self.assert_blocked(self.invoke("session-start"), "session-start")

    def test_session_redacts_secret_like_output(self):
        self.stub("gh", """case "$1 $2" in
          'issue view') echo '{"title":"Issue","body":"TOKEN=synthetic-marker"}';;
          'pr list') echo '[]';;
        esac""")
        result = self.invoke("session-start")
        self.assertNotIn("synthetic-marker", result.stdout + result.stderr)
        self.assertIn("12", result.stdout)

    def test_subagent_report(self):
        for report, allowed in ((REPORT, True), ({}, False),
                                ({**REPORT, "checks_performed": []}, False),
                                ({**REPORT, "findings": ["bad"]}, False)):
            with self.subTest(report=report):
                result = self.invoke("stop-checks", hook_event_name="SubagentStop",
                                     last_assistant_message=json.dumps(report))
                if allowed:
                    self.assertEqual((result.returncode, result.stdout.strip()), (0, ""))
                else:
                    self.assert_blocked(result, "stop-checks")

    def test_stop_needs_passing_checks_even_on_reentry(self):
        result = self.invoke("stop-checks", stop_hook_active=True)
        self.assert_blocked(result, "stop-checks")
        (self.repo / "Makefile").write_text("test:\n\t@echo synthetic-marker\n\t@false\nvalidate:\n\t@true\n")
        self.assert_blocked(self.invoke("stop-checks", stop_hook_active=True), "stop-checks")
        (self.repo / "Makefile").write_text("test validate:\n\t@echo passed >> evidence\n")
        result = self.invoke("stop-checks")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, ""))
        self.assertTrue((self.repo / "evidence").is_file())

    def test_stop_check_timeout(self):
        self.env["LP_HOOK_TIMEOUT_SECONDS"] = "1"
        (self.repo / "Makefile").write_text("test validate:\n\t@sleep 20\n")
        self.assert_blocked(self.invoke("stop-checks"), "stop-checks")
