"""deploy/daily.sh：events 分支有文件、没文件、拉取失败。三种情况维护作业都要被调用。"""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "daily.sh"


class DailySh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.bare = self.root / "origin.git"
        self.job_log = self.root / "job.log"
        self.stub = self.root / "python"
        self.stub.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$LEDGER_JOB_LOG\"\nexit 0\n", encoding="utf-8")
        self.stub.chmod(0o755)
        subprocess.check_call(["git", "init", "--bare", "-b", "events", str(self.bare)], stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "init", "-b", "events", str(self.repo)], stdout=subprocess.DEVNULL)
        self.git("config", "user.email", "daily-sh@example.com")
        self.git("config", "user.name", "daily-sh")
        (self.repo / "README.md").write_text("格式见 docs/events-drafts.md\n", encoding="utf-8")
        (self.repo / "events").mkdir()
        (self.repo / "events" / ".gitkeep").write_text("", encoding="utf-8")
        self.git("add", "README.md", "events/.gitkeep")
        self.git("-c", "user.name=Grok bot", "-c", "user.email=grok-bot@example.com", "commit", "-m", "events")
        self.git("remote", "add", "origin", str(self.bare))
        self.git("push", "-u", "origin", "events")

    def git(self, *args):
        subprocess.check_call(["git", "-C", str(self.repo), *args], stdout=subprocess.DEVNULL)

    def invoke(self, *extra):
        env = {**os.environ, "LEDGER_ROOT": str(self.repo), "LEDGER_PYTHON": str(self.stub), "LEDGER_JOB_LOG": str(self.job_log)}
        return subprocess.run(["bash", str(SCRIPT), "--date", "2026-09-30", *extra], cwd=self.repo, env=env,
                              text=True, capture_output=True, check=False)

    def test_copies_the_file_and_logs_the_commit_and_sha256(self):
        body = "{\"container\":\"地产\"}\n"
        (self.repo / "events" / "2026-09-30.json").write_text(body, encoding="utf-8")
        self.git("add", "events/2026-09-30.json")
        self.git("-c", "user.name=Grok bot", "-c", "user.email=grok-bot@example.com", "commit", "-m", "draft")
        self.git("push", "origin", "events")
        proc = self.invoke("--no-update")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        copied = (self.repo / "data" / "events" / "2026-09-30.json").read_text(encoding="utf-8")
        self.assertEqual(copied, body)
        commit = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "origin/events"], text=True).strip()
        digest = hashlib.sha256(body.encode()).hexdigest()
        self.assertIn(commit, proc.stdout)
        self.assertIn("Grok bot", proc.stdout)
        self.assertIn("grok-bot@example.com", proc.stdout)
        self.assertIn(digest, proc.stdout)
        self.assertIn(digest, (self.repo / "data" / "events" / "2026-09-30.meta.json").read_text(encoding="utf-8"))
        logged = self.job_log.read_text(encoding="utf-8")
        self.assertIn("-m src.jobs daily --maintain-only --rules config/ledger-rules.json --events-dir data/events", logged)
        self.assertIn("--date 2026-09-30", logged)
        self.assertIn("--no-update", logged)

    def test_missing_file_still_runs_the_job(self):
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Grok bot", proc.stdout)
        self.assertIn("grok-bot@example.com", proc.stdout)
        self.assertIn("没有 events/2026-09-30.json", proc.stdout)
        self.assertFalse((self.repo / "data" / "events" / "2026-09-30.json").exists())
        self.assertIn("--maintain-only", self.job_log.read_text(encoding="utf-8"))

    def test_other_author_is_not_copied_and_the_job_still_runs(self):
        body = "{\"container\":\"地产\"}\n"
        (self.repo / "events" / "2026-09-30.json").write_text(body, encoding="utf-8")
        self.git("add", "events/2026-09-30.json")
        self.git("commit", "-m", "not grok")
        self.git("push", "origin", "events")
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("daily-sh", proc.stdout)
        self.assertIn("daily-sh@example.com", proc.stdout)
        self.assertIn("不是 Grok bot", proc.stdout)
        self.assertFalse((self.repo / "data" / "events" / "2026-09-30.json").exists())
        self.assertIn("--maintain-only", self.job_log.read_text(encoding="utf-8"))

    def test_fetch_failure_is_logged_and_the_job_still_runs(self):
        self.git("remote", "set-url", "origin", str(self.root / "missing.git"))
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("拉取 origin/events 失败", proc.stderr)
        self.assertIn("--maintain-only", self.job_log.read_text(encoding="utf-8"))
        self.assertFalse((self.repo / "data" / "events" / "2026-09-30.json").exists())
