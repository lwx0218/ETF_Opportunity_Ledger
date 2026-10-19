"""现金分红：由不复权与 qfq 的阶跃推导，只追加，取数失败不让行情更新失败。"""
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from src.data import db as DB
from src.data import http
from src.data import runner
from src.data.dividends import derive_cash_dividends, ensure, load_dividends, sync_qfq
from src.data.sources import Fetched
from tests.marketdb import open_db, put, put_coverage


def _bar(day, close, open_=None):
    px = close if open_ is None else open_
    return {"date": day, "open": px, "high": px, "low": px, "close": close, "volume": 1.0, "amount": None}


class Derive(unittest.TestCase):
    def test_511260_step_is_the_cash_dividend(self):
        raw = [_bar("2026-09-17", 135.970), _bar("2026-09-18", 134.739)]
        qfq = [_bar("2026-09-17", 134.695), _bar("2026-09-18", 134.739)]
        got = derive_cash_dividends(raw, qfq)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["ex_date"], "2026-09-18")
        self.assertAlmostEqual(got[0]["amount"], 1.275)
        self.assertAlmostEqual(got[0]["prev_close"], 135.970)
        factor = got[0]["prev_close"] / (got[0]["prev_close"] - got[0]["amount"])
        self.assertAlmostEqual(134.739 * factor, 136.014, places=3)

    def test_noise_and_upward_steps_are_ignored(self):
        raw = [_bar("2026-09-17", 10.0), _bar("2026-09-18", 10.001)]
        qfq = [_bar("2026-09-17", 9.0), _bar("2026-09-18", 9.0004)]
        self.assertEqual(derive_cash_dividends(raw, qfq), [])


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.db = self.tmp / "market.sqlite"
        con = open_db(self.db)
        put(con, "511260", pd.DataFrame([_bar("2026-09-17", 135.970), _bar("2026-09-18", 134.739)]), "tencent_etf")
        put_coverage(con, [dict(theme_id="T33", container="国债", status="flagged", exec_code="511260", exec_route="tencent_etf")])
        con.close()

    def test_append_only_and_first_write_wins(self):
        body = ('{"code":0,"data":{"sh511260":{"qfqday":['
                '["2026-09-17","134.7","134.695","134.8","134.6","1"],'
                '["2026-09-18","134.7","134.739","134.8","134.6","1"]]}}}').encode()
        later = ('{"code":0,"data":{"sh511260":{"qfqday":['
                 '["2026-09-17","130","130","130","130","1"],'
                 '["2026-09-18","134.739","134.739","134.739","134.739","1"]]}}}').encode()
        def serve(payload):
            def fake_get(url, params=None, **kw):
                full = url + ("?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()))
                http.LOG.append({"url": full, "fetched_at": "2026-09-18T08:00:00+00:00", "bytes": len(payload),
                                 "sha256": "a" * 64, "error": None, "file": "qfq.body"})
                return payload
            return fake_get

        con = DB.connect(self.db)
        try:
            with mock.patch("src.data.sources.time.sleep"):
                http.LOG.clear()
                with mock.patch.object(http, "get", side_effect=serve(body)):
                    sync_qfq(con, 7, {"511260": date(2026, 9, 1)}, date(2026, 9, 30), log=lambda *_: None)
                self.assertEqual(len(http.LOG), 1)
                self.assertIn("qfq", http.LOG[0]["url"])
                seq = 0
                http.LOG.clear()
                with mock.patch.object(http, "get", side_effect=serve(later)):
                    sync_qfq(con, 8, {"511260": date(2026, 9, 1)}, date(2026, 9, 30), log=lambda *_: None)
            row = con.execute("SELECT amount, prev_close, run_id, request_seq FROM cash_dividends").fetchone()
            self.assertEqual((row["amount"], row["prev_close"], row["run_id"], row["request_seq"]), (1.275, 135.970, 7, seq))
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE cash_dividends SET amount = 9")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("DELETE FROM cash_dividends")
        finally:
            con.close()
        loaded = load_dividends(self.db, ["511260"])
        self.assertEqual(loaded["511260"][0]["ex_date"], "2026-09-18")
        self.assertEqual(load_dividends(self.db, []), {})

    def test_qfq_failure_is_logged_and_writes_nothing(self):
        con = DB.connect(self.db)
        notes = []
        try:
            with mock.patch("src.data.dividends.fetch_tencent", side_effect=http.FetchError("qfq down")):
                sync_qfq(con, 1, {"511260": date(2026, 9, 1)}, date(2026, 9, 30), log=notes.append)
            ensure(con)
            self.assertEqual(con.execute("SELECT count(*) FROM cash_dividends").fetchone()[0], 0)
        finally:
            con.close()
        self.assertTrue(any("qfq down" in line for line in notes))

    def test_update_report_stays_ok_when_qfq_fails(self):
        row = {"theme_id": "T33", "execution_fund_code": "511260"}
        cov = {"exec_code": "511260", "exec_route": "tencent_etf", "theme_id": "T33"}
        fresh = Fetched([_bar("2026-09-17", 135.970), _bar("2026-09-18", 134.739)])

        def route_fn(route, code):
            return lambda b, e: fresh

        with mock.patch("src.data.runner.mvp_targets", return_value=[(row, cov, "exec", "511260", "raw")]), \
             mock.patch("src.data.universe.route_fn", side_effect=route_fn), \
             mock.patch("src.data.dividends.fetch_tencent", side_effect=http.FetchError("qfq down")), \
             mock.patch("src.data.sources.time.sleep"):
            report = runner.update(date(2026, 9, 30), db=self.db, scope="mvp",
                                   dividend_windows={"511260": date(2026, 9, 1)}, log=lambda *_: None)
        self.assertEqual(len(report), 1)
        self.assertTrue(report[0]["ok"])
        self.assertEqual(load_dividends(self.db, ["511260"]), {})
