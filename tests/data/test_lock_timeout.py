"""写库在别人持有读事务时会等到超时上限。sqlite3 默认只等 5 秒，作业会被网页读库打断。"""
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import tests  # noqa: E402,F401

from src.data.db import connect  # noqa: E402
from src.ledger.store import Ledger  # noqa: E402


class LockTimeout(unittest.TestCase):
    def test_write_succeeds_while_a_reader_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            con = connect(path)
            self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 60000)
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            ro = connect(path, readonly=True)
            self.assertEqual(ro.execute("PRAGMA busy_timeout").fetchone()[0], 60000)
            ro.close()

            ready = threading.Event()

            def hold_read():
                reader = sqlite3.connect(path)
                reader.execute("BEGIN")
                reader.execute("SELECT value FROM meta LIMIT 1").fetchone()
                ready.set()
                time.sleep(2)
                reader.commit()
                reader.close()

            holder = threading.Thread(target=hold_read)
            holder.start()
            self.assertTrue(ready.wait(5))
            started = time.monotonic()
            con.execute("INSERT INTO meta (key, value) VALUES ('probe', 'ok')")
            con.commit()
            waited = time.monotonic() - started
            row = con.execute("SELECT value FROM meta WHERE key = 'probe'").fetchone()
            con.close()
            holder.join(5)
            self.assertEqual(row[0], "ok")
            self.assertGreaterEqual(waited, 1.5)

            ledger = Path(tmp) / "ledger.sqlite"
            book = Ledger(ledger, clock=lambda: "2026-10-09T16:05", replay=True)
            try:
                self.assertEqual(book.conn.execute("PRAGMA busy_timeout").fetchone()[0], 60000)
                self.assertEqual(book.conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            finally:
                book.close()
