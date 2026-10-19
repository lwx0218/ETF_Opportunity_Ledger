"""--maintain-only：没有启用规则也能记账，不扫描，不创建缺失的正式库。"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from src.data import db as DB
from src.jobs.daily import DayReport
from src.jobs.__main__ import main as jobs_main
from src.ledger.store import ROOT, Ledger


class MaintainOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.market = self.root / "market.sqlite"
        self.ledger = self.root / "ledger.sqlite"
        con = DB.connect(self.market)
        DB.load_calendar(con, [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)])
        con.close()
        self.rules = ROOT / "config" / "ledger-rules.json"

    def args(self, day, db=None):
        return ["daily", "--maintain-only", "--no-update", "--date", day, "--market", str(self.market),
                "--db", str(db or self.ledger), "--rules", str(self.rules)]

    def test_missing_ledger_is_not_created(self):
        missing = self.root / "absent.sqlite"
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(self.args("2026-09-28", missing)), 3)
        self.assertFalse(missing.exists())

    def test_empty_rules_mark_a_day_and_a_rerun_stays_put(self):
        Ledger(self.ledger).close()
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(self.args("2026-09-28")), 0)
            self.assertEqual(jobs_main(self.args("2026-09-28")), 0)
        with self.assertRaises(SystemExit):
            jobs_main(["daily", "--no-update", "--date", "2026-09-29", "--market", str(self.market),
                       "--db", str(self.ledger), "--rules", str(self.rules)])
        ledger = Ledger(self.ledger)
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.processed_days(), {"2026-09-28"})

    def test_open_cards_skip_the_scan(self):
        Ledger(self.ledger).close()
        report = DayReport("2026-09-28")
        held = [{"id": "T-2026-001", "container": "地产", "instrument_code": "512200"}]
        with mock.patch("src.jobs.__main__.open_cards", return_value=held), \
             mock.patch("src.jobs.__main__.execution_panel", return_value=(None, None, None, None)), \
             mock.patch("src.jobs.__main__.preflight_open", return_value=[]), \
             mock.patch("src.jobs.__main__.DailyJob") as job, \
             mock.patch("builtins.print"):
            job.return_value.run.return_value = report
            self.assertEqual(jobs_main(self.args("2026-09-28")), 0)
        self.assertEqual(job.return_value.run.call_args.kwargs["maintain_only"], True)
        self.assertEqual(job.call_args.kwargs["rules"], {"事件驱动": {}})
        self.assertEqual(job.call_args.kwargs["instruments"]["地产"]["code"], "512200")
        ledger = Ledger(self.ledger)
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.processed_days(), {"2026-09-28"})
        cfg = json.loads(self.rules.read_text(encoding="utf-8"))
        self.assertEqual((cfg["事件驱动"]["enabled"], cfg["恐慌下轨"]["enabled"]), (True, False))
