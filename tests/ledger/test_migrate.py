"""v1.1-i 的库补上 v1.1-j 的表。重复跑不改已有行。"""
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.ledger.store import SCHEMA_VERSION, Ledger, migrate


def _dump(path):
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: con.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall() for name in names}
    finally:
        con.close()


class Migrate(unittest.TestCase):
    def test_twice_on_an_r5_database_keeps_existing_rows(self):
        old = subprocess.check_output(["git", "show", "4b130fa:src/ledger/schema.sql"], text=True)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ledger.sqlite"
        con = sqlite3.connect(path)
        con.create_function("ledger_now", 0, lambda: "2026-09-30T16:00")
        con.executescript(old)
        con.execute("INSERT INTO ledger_meta (key, value) VALUES ('clock', 'real')")
        con.execute("INSERT INTO ledger_meta (key, value) VALUES ('schema', 'v1.1-i')")
        con.execute("INSERT INTO job_days (day, recorded_at) VALUES ('2026-09-28', '2026-09-30T16:00')")
        con.execute("INSERT INTO ew_daily (date, ew_return, ew_level, n_containers, recorded_at) "
                    "VALUES ('2026-09-28', 0, 1, 4, '2026-09-30T16:00')")
        con.commit()
        con.close()
        before = _dump(path)
        self.assertEqual(migrate(path), "v1.1-i")
        mid = _dump(path)
        self.assertEqual(migrate(path), SCHEMA_VERSION)
        after = _dump(path)
        self.assertEqual(mid, after)
        self.assertEqual(mid["job_days"], before["job_days"])
        self.assertEqual(mid["ew_daily"], before["ew_daily"])
        self.assertEqual(mid["ledger_meta"], [("clock", "real"), ("schema", SCHEMA_VERSION)])
        self.assertEqual(mid["spot_checks"], [])
        self.assertEqual(mid["event_drafts"], [])
        opened = Ledger(path)
        self.addCleanup(opened.close)
        self.assertEqual(opened.conn.execute("SELECT value FROM ledger_meta WHERE key = 'schema'").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual([tuple(r) for r in opened.conn.execute("SELECT day FROM job_days")], [("2026-09-28",)])
        self.assertEqual([tuple(r) for r in opened.conn.execute("SELECT date, ew_level FROM ew_daily")], [("2026-09-28", 1.0)])
