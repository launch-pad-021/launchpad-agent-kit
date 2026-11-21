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
        inputs = {key: content}
        if hook == "guard-paths":
            inputs["content"] = "sample"
        return self.invoke(hook, role, tool_input=inputs)

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
        result = self.invoke("guard-paths", hook_event_name="PostToolUse", tool_input={"file_path": str(target), "content": "package scoped"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("formatted", target.read_text())

    def stub(self, program, body):
        path = self.bin / program
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def test_session_context(self):
        self.stub("gh", """case "$1 $2" in
          api*) echo '{"author_association":"OWNER","title":"Review map","body":"Check the map"}';;
          'pr list') echo '[{"number":42}]';;
          'pr view') echo '{"comments":[{"authorAssociation":"OWNER","body":"### Handoff — run 1; map ready"}]}';;
        esac""")
        (self.repo / "src").mkdir()
        result = self.invoke("session-start")
        for item in ("12", "src", "Review map", "map ready"):
            self.assertIn(item, result.stdout)
        self.env.pop("LP_ISSUE_NUMBER")
        self.assert_blocked(self.invoke("session-start"), "session-start")

    def test_session_redacts_secret_like_output(self):
        self.stub("gh", """case "$1 $2" in
          api*) echo '{"author_association":"OWNER","title":"Issue","body":"TOKEN=synthetic-marker"}';;
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

    def test_edit_payload_validation_and_redaction(self):
        for tool, inputs, allowed in (
            ("Write", {"file_path": "a.txt"}, False),
            ("Write", {"file_path": "a.txt", "content": "PASSWORD=synthetic-marker"}, False),
            ("Edit", {"file_path": "a.txt", "new_string": ""}, False),
            ("Edit", {"file_path": "a.txt", "new_string": "ok", "old_string": "old"}, True),
            ("MultiEdit", {"file_path": "a.txt", "edits": []}, False),
            ("MultiEdit", {"file_path": "a.txt", "edits": [{"old_string": "x", "new_string": "y"}]}, True),
        ):
            with self.subTest(tool=tool, keys=list(inputs)):
                result = self.invoke("guard-paths", tool_name=tool, tool_input=inputs)
                if allowed:
                    self.assertEqual(result.returncode, 0)
                else:
                    self.assert_blocked(result, "guard-paths")

    def test_stop_redacts_final_message_and_checks_each_changed_language(self):
        (self.repo / "Makefile").write_text("test validate:\n\t@true\n")
        result = self.invoke("stop-checks", last_assistant_message="PASSWORD=synthetic-marker")
        self.assert_blocked(result, "stop-checks")
        for package, manifest in (("backend", "go.mod"), ("worker", "Cargo.toml"),
                                  ("client", "package.json"), ("batch", "pyproject.toml")):
            root = self.repo / package
            root.mkdir()
            (root / manifest).touch()
        for name in ("go", "gofmt", "cargo", "npx", "uv"):
            self.stub(name, 'echo "${0##*/} $*" >> ran')
        result = self.invoke("stop-checks")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        for package, expected in {
            "backend": ("gofmt", "go vet", "go test"), "worker": ("cargo fmt", "cargo clippy", "cargo test"),
            "client": ("prettier", "eslint", "tsc", "vitest"), "batch": ("ruff format", "ruff check", "pyright", "pytest"),
        }.items():
            with self.subTest(package=package):
                log = (self.repo / package / "ran").read_text()
                for name in expected:
                    self.assertIn(name, log)

    def test_context_is_a_git_workspace_and_json_is_strict(self):
        self.env["CLAUDE_PROJECT_DIR"] = str(self.temp)
        result = self.invoke("guard-bash", cwd=str(self.temp), tool_input={"command": "pwd"})
        self.assert_blocked(result, "guard-bash")
        self.env["CLAUDE_PROJECT_DIR"] = str(self.repo)
        raw = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_type": "implementer",
                          "cwd": str(self.repo), "tool_input": {"command": "pwd"}, "extra": float("nan")})
        self.assert_blocked(self.invoke("guard-bash", raw=raw), "guard-bash")

    def test_git_write_scope_and_safe_read_arguments(self):
        path = self.repo / "src.txt"
        path.write_text("test")
        results = (("git add -- src.txt", True), ("git diff -- src.txt", True),
                   ("git push --force-with-lease origin main", False), ("git push origin HEAD:main", False),
                   ("git add -- .", False), ("git diff -- .env.local", False))
        for command, allowed in results:
            with self.subTest(command=command):
                self.assertEqual(self.tool("guard-bash", command).returncode, 0 if allowed else 2)
        subprocess.run(["git", "add", "src.txt"], cwd=self.repo, check=True)
        self.assertEqual(self.tool("guard-bash", "git commit -m 'test: document scope'").returncode, 0)
        (self.repo / ".github").mkdir()
        (self.repo / ".github/x").touch()
        subprocess.run(["git", "add", ".github/x"], cwd=self.repo, check=True)
        self.assert_blocked(self.tool("guard-bash", "git commit -m 'test: verify staging'"), "guard-bash")

    def test_untrusted_issue_and_handoff(self):
        self.stub("gh", """case "$1 $2" in
          api*) echo '{"author_association":"NONE","title":"synthetic-marker"}';;
          'pr list') echo '[]';;
        esac""")
        self.assert_blocked(self.invoke("session-start"), "session-start")
        self.stub("gh", """case "$1 $2" in
          api*) echo '{"author_association":"OWNER","title":"Source","body":"Notes"}';;
          'pr list') echo '[{"number":42}]';;
          'pr view') echo '{"comments":[{"authorAssociation":"NONE","author":{"login":"other[bot]"},"body":"### Handoff synthetic-marker"}]}';;
        esac""")
        result = self.invoke("session-start")
        self.assertIn("No prior handoff", result.stdout)
        self.assertNotIn("synthetic-marker", result.stdout + result.stderr)

    def test_runtime_startup_failure_has_event_specific_decision(self):
        self.stub("python3", "exit 2")
        for hook in EVENTS:
            with self.subTest(hook=hook):
                self.assert_blocked(self.invoke(hook), hook)

    def test_project_commands_and_github_argument_boundaries(self):
        for command in ("echo 'checks complete'", "ls -l", "git branch --show-current", "git rev-parse HEAD",
                        "git switch -c agent/12-new", "gh issue view 12 --json title,body",
                        "gh pr view 4 --comments", "gh issue list", "gh pr create --fill",
                        "gh pr create --title 'Safe change' --body 'Ran checks'", "uv sync --frozen",
                        "cargo fetch --locked", "go mod download", "uv run pytest", "buf lint"):
            with self.subTest(command=command):
                self.assertEqual(self.tool("guard-bash", command).returncode, 0)
        for command in ("echo PASSWORD=synthetic-marker", "gh pr create --body-file credentials",
                        "gh api arbitrary", "gh pr view --repo other/repo", "git switch -c agent/99-other",
                        "git log --output=marker", "git status --git-dir elsewhere", "git commit --amend",
                        "npm ci --script-shell other"):
            with self.subTest(command=command):
                self.assert_blocked(self.tool("guard-bash", command), "guard-bash")
        for role, cmd, allowed in (("correctness-verifier", "go test ./...", True),
                                   ("code-reviewer", "go test ./...", False),
                                   ("code-reviewer", "npm ci --ignore-scripts", False),
                                   ("planner", "go mod download", False)):
            with self.subTest(role=role, cmd=cmd):
                self.assertEqual(self.tool("guard-bash", cmd, role).returncode, 0 if allowed else 2)

    def test_feature_branch_push_checks_committed_paths(self):
        def git(*args):
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
                           cwd=self.repo, check=True, capture_output=True)
        git("commit", "--allow-empty", "-m", "base")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        (self.repo / "code.txt").touch()
        git("add", "code.txt")
        git("commit", "-m", "change")
        command = "git push -u origin agent/12-hook"
        self.assertEqual(self.tool("guard-bash", command).returncode, 0)
        (self.repo / ".github").mkdir()
        (self.repo / ".github/check.yml").touch()
        git("add", ".github/check.yml")
        git("commit", "-m", "config")
        self.assert_blocked(self.tool("guard-bash", command), "guard-bash")
