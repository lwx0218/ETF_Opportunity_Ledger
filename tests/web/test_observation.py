"""两页隔离演示的合成行情与原生命周期使用同一价格，不访问正式库。"""
import sqlite3
import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.observation import observe
from src.web.demo import DAYS, INITIAL_DAY, INSTRUMENTS, synthetic_panel
from src.web.demo_observation import SOURCE, demo_market


class DemoObservationTests(unittest.TestCase):
    def test_provider_only_connects_to_memory_and_returns_readonly_synthetic_pool(self):
        original_connect = sqlite3.connect
        opened = []

        def connect(path, *args, **kwargs):
            self.assertEqual(path, ":memory:")
            opened.append(path)
            return original_connect(path, *args, **kwargs)

        with patch("src.web.demo_observation.sqlite3.connect", side_effect=connect), \
                patch("src.data.db.connect", side_effect=AssertionError("不允许打开行情库")), \
                patch("src.jobs.daily.DailyJob.run", side_effect=AssertionError("不允许扫描")):
            with demo_market() as con:
                self.assertEqual(con.execute("SELECT count(*) FROM universe").fetchone()[0], 37)
                self.assertEqual(con.execute("SELECT count(*) FROM coverage_latest").fetchone()[0], 37)
                self.assertEqual(con.execute("SELECT DISTINCT source FROM bars").fetchall()[0][0], SOURCE)
                self.assertEqual(con.execute("SELECT value FROM meta WHERE key='observation_mode'").fetchone()[0], "synthetic")
                self.assertEqual(con.execute("SELECT count(*) FROM bars WHERE amount IS NOT NULL").fetchone()[0], 0)
                self.assertEqual(con.execute("SELECT count(*) FROM bars WHERE code NOT LIKE 'DEMO-%' AND code<>'H00300'").fetchone()[0], 0)
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute("DELETE FROM bars")
        self.assertEqual(opened, [":memory:"])
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

    def test_six_ledger_containers_and_benchmark_keep_exact_demo_prices(self):
        panel, benchmark = synthetic_panel()
        with demo_market() as con:
            for name, instrument in INSTRUMENTS.items():
                expected = panel[panel["container"] == name]
                for code in (instrument["code"], instrument["research_code"]):
                    rows = con.execute("SELECT date,open,high,low,close,volume FROM bars "
                                       "WHERE code=? AND date>=? ORDER BY date", (code, DAYS[0])).fetchall()
                    self.assertEqual([r["date"] for r in rows], list(DAYS))
                    self.assertEqual(len(rows), len(expected))
                    for actual, (_, sample) in zip(rows, expected.iterrows()):
                        for key in ("open", "high", "low", "close", "volume"):
                            self.assertEqual(actual[key], sample[key])
            rows = con.execute("SELECT close FROM bars WHERE code='H00300' AND date>=? ORDER BY date", (DAYS[0],))
            self.assertEqual([row[0] for row in rows], list(benchmark))

    def test_observer_uses_replay_cutoff_and_labels_synthetic_provenance(self):
        now = datetime.fromisoformat(f"{INITIAL_DAY}T16:00").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        with demo_market() as con:
            result = observe(con, date.fromisoformat(INITIAL_DAY), now=now, weeks=1, theme_id="T06")
        self.assertEqual(result["effective_date"], INITIAL_DAY)
        self.assertEqual(result["comparison"]["pool"], 37)
        self.assertTrue(result["synthetic"])
        self.assertIn("非官方", result["calendar_basis"])
        self.assertFalse(result["research_ready"])
        detail = result["detail"]
        self.assertEqual(detail["identity"]["code"], INSTRUMENTS["半导体"]["research_code"])
        self.assertEqual(detail["identity"]["source"], SOURCE)
        self.assertEqual(detail["chart"][-1]["date"], INITIAL_DAY)
        self.assertTrue(all(row["date"] <= INITIAL_DAY for row in detail["chart"]))
        self.assertTrue(detail["fields"]["state"]["available"])
        self.assertTrue(detail["fields"]["rs_1m"]["available"])
        self.assertEqual(detail["fields"]["rs_1m"]["benchmark"]["source"], SOURCE)
        self.assertEqual(detail["volume"]["unit"], "unverified")
        self.assertTrue(all(row["volume"] is None for row in detail["chart"]))
