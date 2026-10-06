"""演示通过真实台账与每日流程走完生命周期，不触碰正式行情。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.jobs.daily import DailyJob
from src.ledger.store import APPEND_ONLY, ROOT, Ledger, LedgerError
from src.web.demo import DAYS, INITIAL_DAY, INSTRUMENTS, DemoStore, synthetic_panel


class SyntheticPanelTests(unittest.TestCase):
    def test_prewarmed_indicators_follow_synthetic_prices_without_fabricating_month_z(self):
        panel, bench = synthetic_panel()
        self.assertEqual(len(panel), len(DAYS) * len(INSTRUMENTS))
        self.assertEqual(list(bench.index.strftime("%Y-%m-%d")), list(DAYS))
        self.assertEqual(bench.iloc[0], 4000)
        self.assertTrue(panel["z_month"].isna().all())
        self.assertTrue(panel[["atr20", "rs_1m"]].notna().all().all())
        self.assertTrue((panel["volume"] > 0).all())
        self.assertTrue((panel["low"] <= panel["open"]).all())
        self.assertTrue((panel["open"] <= panel["close"]).all())
        self.assertTrue((panel["close"] <= panel["high"]).all())
        for j, name in enumerate(INSTRUMENTS):
            rows = panel[panel["container"] == name]
            self.assertEqual(list(rows["date"].dt.strftime("%Y-%m-%d")), list(DAYS))
            first = rows.iloc[0]
            step, close = .12 + .01 * j, 100 + 10 * j
            # Constant intraday range and known 21-session prehistory give closed-form expectations.
            self.assertAlmostEqual(first["atr20"], 2 + step)
            self.assertAlmostEqual(first["rs_1m"], close / (close - 21 * step) - 4000 / 3979)
            # Rising averages plus the low touching EMA20 is XB, not the old hard-coded TREND_UP.
            self.assertEqual(set(rows["state"]), {"XB"})
        again, again_bench = synthetic_panel()
        pd.testing.assert_frame_equal(panel, again)
        pd.testing.assert_series_equal(bench, again_bench)


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.demo = DemoStore(self.tmp.name)
        self.demo.ensure()

    def rows(self):
        with self.demo.open_ledger() as ledger:
            return {table: [tuple(row) for row in ledger.conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
                    for table in APPEND_ONLY}

    def test_seed_is_reproducible_and_restart_keeps_clock_and_states(self):
        with self.demo.open_ledger() as ledger:
            self.assertEqual(ledger.summary()["by_status"],
                             {"作废": 1, "候选": 2, "已结": 1, "当下": 1, "过去": 1})
            self.assertEqual(ledger.summary()["denominator"], 6)
            self.assertEqual(ledger.processed_days(), set(DAYS[:31]))
            self.assertEqual(ledger.conn.execute("SELECT count(*) FROM evidence").fetchone()[0], 0)
            self.assertEqual(ledger.conn.execute("SELECT count(*) FROM daily WHERE z IS NOT NULL").fetchone()[0], 0)
            self.assertEqual(ledger.conn.execute("SELECT count(*) FROM daily WHERE rs_1m_rank IS NULL").fetchone()[0], 0)
            for card_id in ledger.cards_in("候选", "当下", "过去", "已结", "作废"):
                self.assertTrue(ledger.card(card_id)["thesis"].startswith("演示："))
        before = self.rows()
        untouched = self.demo.path.read_bytes()
        restarted = DemoStore(self.tmp.name)
        restarted.ensure()
        self.assertEqual(restarted.now(), f"{INITIAL_DAY}T16:00")
        self.assertEqual(restarted.path.read_bytes(), untouched)
        restarted.advance()
        self.assertEqual(DemoStore(self.tmp.name).now(), f"{DAYS[31]}T16:00")
        self.demo.reset()
        self.assertEqual(self.rows(), before)

    def test_score_void_signal_next_open_fill_and_twenty_day_tracking(self):
        with self.demo.open_ledger() as ledger:
            ledger.owner_score("T-2026-005", 1, "演示：没有真实证据，独立给低分。")
            with self.assertRaises(LedgerError):
                ledger.owner_score("T-2026-005", 2, "重复评分必须拒绝")
            ledger.void("T-2026-006", "演示：候选判断不成立，保留分母")
            close = ledger.daily_rows("T-2026-004")[-1]["close"]
            ledger.signal_exit("T-2026-004", INITIAL_DAY, "手动", close, "演示：主动退出")
            self.assertEqual(ledger.status("T-2026-004"), "当下")
            self.assertIsNone(ledger.conn.execute("SELECT * FROM exits WHERE card_id='T-2026-004'").fetchone())
        report = self.demo.advance()
        self.assertEqual(report["exits"], ["T-2026-004"])
        self.assertEqual(report["entries"], ["T-2026-005"])
        with self.demo.open_ledger() as ledger:
            self.assertEqual(ledger.status("T-2026-004"), "过去")
            with self.assertRaises(LedgerError):
                ledger.owner_score("T-2026-006", 1, "过期评分必须拒绝")
        for _ in range(19):
            self.demo.advance()
        with self.demo.open_ledger() as ledger:
            self.assertEqual(ledger.status("T-2026-004"), "过去")
        self.demo.advance()
        with self.demo.open_ledger() as ledger:
            self.assertEqual(ledger.status("T-2026-004"), "已结")
            self.assertEqual(ledger.status("T-2026-003"), "已结")
            self.assertEqual(ledger.summary()["denominator"], 6)
            self.assertEqual(ledger.summary()["by_status"]["作废"], 2)

    def test_frozen_fields_and_invalid_actions_use_domain_guards(self):
        with self.demo.open_ledger() as ledger:
            with self.assertRaises(sqlite3.IntegrityError):
                ledger.conn.execute("UPDATE cards SET thesis='修改预测' WHERE id='T-2026-005'")
            with self.assertRaises(LedgerError):
                ledger.void("T-2026-004", "已经进场不能删出分母")
            with self.assertRaises(LedgerError):
                ledger.signal_exit("T-2026-005", INITIAL_DAY, "手动", 100, "候选没有持仓")
            with self.assertRaises(LedgerError):
                ledger.signal_exit("T-2026-004", INITIAL_DAY, "跟踪期满", 100)

    def test_daily_repeat_does_not_create_rows(self):
        before = self.rows()
        with self.demo.open_ledger() as ledger:
            panel, bench = synthetic_panel()
            report = self.demo._job(ledger, panel, bench).run(INITIAL_DAY)
            ledger.mark_processed(INITIAL_DAY)
        self.assertFalse(report.changed())
        self.assertEqual(self.rows(), before)

    def test_partial_advance_and_failed_reset_preserve_existing_file_and_clock(self):
        before = self.demo.path.read_bytes()
        with patch.object(Ledger, "mark_processed", side_effect=RuntimeError("模拟提交前中断")):
            with self.assertRaisesRegex(RuntimeError, "模拟"):
                self.demo.advance()
        self.assertEqual(self.demo.path.read_bytes(), before)
        self.assertEqual(self.demo.now(), f"{INITIAL_DAY}T16:00")
        with patch.object(DailyJob, "run", side_effect=RuntimeError("初始化中断")):
            with self.assertRaisesRegex(RuntimeError, "初始化"):
                self.demo.reset()
        self.assertEqual(self.demo.path.read_bytes(), before)
        self.assertEqual(list(Path(self.tmp.name).glob(".demo-*")), [])

    def test_formal_paths_symlinks_and_unknown_existing_files_are_refused(self):
        with self.assertRaisesRegex(LedgerError, "data"):
            DemoStore(ROOT / "data")
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        path = other / "ledger.sqlite"
        path.write_bytes(b"not a demo database")
        for action in ("ensure", "reset", "advance"):
            with self.assertRaises(LedgerError):
                getattr(DemoStore(other), action)()
            self.assertEqual(path.read_bytes(), b"not a demo database")
        path.unlink()
        path.symlink_to(self.demo.path)
        with self.assertRaisesRegex(LedgerError, "符号链接"):
            DemoStore(other)

    def test_existing_real_clock_ledger_is_not_reset(self):
        other = Path(self.tmp.name) / "real-clock"
        other.mkdir()
        ledger = Ledger(other / "ledger.sqlite")
        ledger.close()
        before = (other / "ledger.sqlite").read_bytes()
        with self.assertRaisesRegex(LedgerError, "不是本应用"):
            DemoStore(other).reset()
        self.assertEqual((other / "ledger.sqlite").read_bytes(), before)

    def test_previous_demo_version_requires_explicit_new_directory(self):
        other = Path(self.tmp.name) / "previous-demo"
        with patch("src.web.demo.DEMO_VERSION", "web-demo-v1"):
            previous = DemoStore(other)
            previous.ensure()
        before = previous.path.read_bytes()
        for action in ("ensure", "reset", "advance"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(LedgerError, "不是本应用"):
                    getattr(DemoStore(other), action)()
                self.assertEqual(previous.path.read_bytes(), before)
