"""离线合成输入质量门禁：只连接临时库，不抓行情、不运行真实研究。"""
from datetime import date
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import pandas as pd

from src.data import db as DB, quality, runner
from src.data.__main__ import main
from src.indicators import build as B
from src.indicators.__main__ import main as indicators_main


END = date(2005, 1, 10)
DAYS = pd.bdate_range("2005-01-04", END.isoformat()).strftime("%Y-%m-%d").tolist()


class Quality(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.tmp = Path(self.scratch.name)
        self.db = self.tmp / "market.sqlite"

    def fixture(self, *, days=None, calendar=None, containers=None):
        """仅声明测试所用容器；数字是构造值，日历也是合成输入。"""
        days = DAYS if days is None else days
        calendar = pd.bdate_range("2005-01-04", "2005-01-14").strftime("%Y-%m-%d").tolist() if calendar is None else calendar
        containers = [dict(theme_id="T01", container="沪深300", status="retained", code="000300",
                           series_code="H00300", series_adj="raw", route_used="csi", first_date=days[0],
                           price_only="False")] if containers is None else containers
        con = DB.connect(self.db)
        DB.load_universe(con, [{"theme_id": c["theme_id"], "theme": c["container"], "status": c["status"]}
                               for c in containers], "synthetic-quality-universe")
        run = DB.start_run(con, "backfill")
        DB.write_coverage(con, run, containers)
        DB.finish_run(con, run)
        with con:
            con.executemany("INSERT INTO calendar VALUES (?)", [(d,) for d in calendar])
            con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [("H00300", "raw", d, 90.0 + i, 110.0 + i, 80.0 + i, 100.0 + i,
                              None, None, "csi", "2005-02-01T00:00:00+00:00") for i, d in enumerate(days)])
        con.close()

    def mutate(self, sql, args=()):
        con = DB.connect(self.db)
        with con:
            con.execute(sql, args)
        con.close()

    def change_bar(self, day, **changes):
        con = DB.connect(self.db)
        row = dict(con.execute("SELECT * FROM bars WHERE code='H00300' AND date=?", (day,)).fetchone())
        row.update(changes)
        with con:
            con.execute("DELETE FROM bars WHERE code='H00300' AND date=?", (day,))
            con.execute("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
        con.close()

    def report(self, *, end=END, start=None):
        before = DB.sha256_file(self.db)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("quality must remain offline")):
            report = quality.preflight(self.db, end, start=start)
        self.assertEqual(DB.sha256_file(self.db), before, "只读预检不得改变原库的任何字节")
        return report

    def package(self, end=END):
        return runner.package(end, db=self.db, pkg_root=self.tmp / "package" / self.db.stem, log=lambda *_: None)

    def assert_build_refuses_without_outputs(self, package, *, start=None):
        out = self.tmp / "nested" / "panel.sqlite"
        before = DB.sha256_file(package)
        with self.assertRaises(B.BuildError):
            B.build(package, out, start=start, log=lambda *_: None)
        self.assertFalse(out.exists())
        self.assertFalse(out.with_name(out.name + ".tmp").exists())
        self.assertFalse(B.report_path(out).exists())
        self.assertEqual(DB.sha256_file(package), before)

    def test_complete_real_ohlc_is_ready(self):
        self.fixture()
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertTrue(report["research_ready"])
        self.assertEqual(report["benchmark"]["missing_close_dates"], [])

    def test_pre2005_history_is_preserved_by_default_and_explicit_windows(self):
        calendar = pd.bdate_range("2004-12-27", "2005-01-14").strftime("%Y-%m-%d").tolist()
        days = [d for d in calendar if d <= END.isoformat()]
        self.fixture(days=days, calendar=calendar)
        pkg = self.package()
        for start in (None, date(2004, 12, 29)):
            with self.subTest(start=start):
                resolved = calendar[0] if start is None else start.isoformat()
                expected = [d for d in days if d >= resolved]
                report = self.report(start=start)
                self.assertTrue(report["benchmark_ready"])
                self.assertTrue(report["research_ready"])
                self.assertEqual(report["benchmark"]["first"], expected[0])
                self.assertEqual(report["containers"]["T01"]["first"], expected[0])
                self.assertEqual(report["requested_window"], {
                    "start": None if start is None else start.isoformat(), "end": END.isoformat()})
                self.assertEqual(report["trusted_calendar_range"], {"start": calendar[0], "end": calendar[-1]})
                self.assertEqual(report["effective_window"], {
                    "start": resolved, "end": END.isoformat(),
                    "first_trading_day": expected[0], "last_trading_day": expected[-1]})
                self.assertEqual((report["start"], report["end"]), (resolved, END.isoformat()))
                out = B.build(pkg, self.tmp / f"panel-{resolved}.sqlite", start=start, log=lambda *_: None)
                with sqlite3.connect(out) as con:
                    self.assertEqual(con.execute("SELECT date FROM panel ORDER BY date").fetchall(), [(d,) for d in expected])
                    self.assertEqual(con.execute("SELECT date FROM bench ORDER BY date").fetchall(), [(d,) for d in expected])
                    meta = dict(con.execute("SELECT key, value FROM meta"))
                built = json.loads(B.report_path(out).read_text())
                for field in ("requested_window", "trusted_calendar_range", "effective_window"):
                    self.assertEqual(built["input_quality"][field], report[field])
                    self.assertEqual(json.loads(meta[field]), report[field])

    def test_pre2005_missing_close_is_checked_without_year_cutoff(self):
        calendar = pd.bdate_range("2004-12-27", "2005-01-14").strftime("%Y-%m-%d").tolist()
        self.fixture(days=[d for d in calendar if d <= END.isoformat()], calendar=calendar)
        self.mutate("DELETE FROM bars WHERE date='2004-12-29'")
        report = self.report()
        self.assertFalse(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertEqual(report["benchmark"]["missing_close_dates"], ["2004-12-29"])
        self.assertEqual(report["containers"]["T01"]["missing_close_dates"], ["2004-12-29"])
        self.assert_build_refuses_without_outputs(self.package())

    def test_explicit_window_excludes_earlier_holes_for_preflight_and_build_cli(self):
        self.fixture()
        self.mutate("DELETE FROM bars WHERE date=?", (DAYS[0],))
        self.assertFalse(self.report()["research_ready"])
        start = date.fromisoformat(DAYS[1])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["preflight", "--db", str(self.db), "--start", start.isoformat(), "--end", END.isoformat()])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report, self.report(start=start))
        pkg = self.package()
        out = self.tmp / "cli-panel.sqlite"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(indicators_main(["build", "--package", str(pkg), "--out", str(out),
                                              "--start", start.isoformat()]), 0)
        built = json.loads(B.report_path(out).read_text())
        self.assertEqual(built["input_quality"], report)
        with sqlite3.connect(out) as con:
            self.assertEqual(con.execute("SELECT date FROM panel ORDER BY date").fetchall(), [(d,) for d in DAYS[1:]])
            self.assertEqual(con.execute("SELECT date FROM bench ORDER BY date").fetchall(), [(d,) for d in DAYS[1:]])

    def test_explicit_weekend_start_is_preserved_and_slices_official_days(self):
        self.fixture()
        self.mutate("INSERT INTO bars VALUES ('H00300', 'raw', '2005-01-08', NULL, NULL, NULL, 999999, NULL, NULL, 'csi', 'test')")
        start = date(2005, 1, 8)
        report = self.report(start=start)
        self.assertTrue(report["research_ready"])
        self.assertEqual(report["effective_window"], {
            "start": "2005-01-08", "end": "2005-01-10",
            "first_trading_day": "2005-01-10", "last_trading_day": "2005-01-10"})
        self.assertEqual(report["containers"]["T01"]["excluded_non_trading_dates"], ["2005-01-08"])
        out = B.build(self.package(), self.tmp / "weekend-start.sqlite", start=start, log=lambda *_: None)
        with sqlite3.connect(out) as con:
            self.assertEqual(con.execute("SELECT date FROM panel").fetchall(), [("2005-01-10",)])
        built = json.loads(B.report_path(out).read_text())
        self.assertEqual(built["input_quality"], report)
        self.assertEqual(built["containers"]["沪深300"]["dropped_off_calendar"], 1)

    def test_requests_outside_trusted_calendar_fail_including_new_year(self):
        self.fixture()
        pkg = self.package()
        for start in (date(2005, 1, 1), date(2005, 1, 3)):
            with self.subTest(start=start):
                report = self.report(start=start)
                self.assertFalse(report["benchmark_ready"])
                self.assertFalse(report["research_ready"])
                self.assertIn("覆盖", " ".join(report["issues"]))
                self.assertEqual(report["requested_window"]["start"], start.isoformat())
                self.assert_build_refuses_without_outputs(pkg, start=start)
        report = self.report(end=date(2005, 1, 17))
        self.assertFalse(report["research_ready"])
        self.assertIn("覆盖", " ".join(report["issues"]))
        self.assert_build_refuses_without_outputs(self.package(end=date(2005, 1, 17)))

    def test_close_only_benchmark_does_not_release_strategy(self):
        self.fixture()
        for day in DAYS:
            self.change_bar(day, open=None, high=None, low=None)
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertFalse(report["containers"]["T01"]["research_ready"])
        self.assertEqual(report["containers"]["T01"]["missing_ohl_dates"], DAYS)
        self.assert_build_refuses_without_outputs(self.package())

    def test_dates_outside_trusted_coverage_are_not_labeled_non_trading(self):
        outside = ["2004-12-31", "2005-01-17"]
        self.fixture(days=[outside[0], *DAYS, outside[1]])
        start, end = date(2004, 12, 31), date(2005, 1, 17)
        report = self.report(start=start, end=end)
        self.assertFalse(report["research_ready"])
        for item in (report["benchmark"], report["containers"]["T01"]):
            self.assertEqual(item["outside_trusted_calendar_dates"], outside)
            self.assertEqual(item["excluded_non_trading_dates"], [])
        self.assert_build_refuses_without_outputs(self.package(end=end), start=start)

    def test_three_year_end_close_holes_are_explicit(self):
        missing = ["2008-12-31", "2009-12-31", "2010-12-31"]
        calendar = pd.bdate_range("2005-01-04", "2011-01-07").strftime("%Y-%m-%d").tolist()
        days = [d for d in calendar if d <= "2010-12-31" and d not in missing]
        self.fixture(days=days, calendar=calendar)
        report = self.report(end=date(2010, 12, 31))
        self.assertFalse(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertEqual(report["benchmark"]["missing_close_dates"], missing)
        self.assertEqual(report["containers"]["T01"]["missing_close_dates"], missing)

    def test_missing_first_and_last_benchmark_dates_block(self):
        self.fixture()
        self.mutate("DELETE FROM bars WHERE date IN (?, ?)", (DAYS[0], DAYS[-1]))
        report = self.report()
        self.assertEqual(report["benchmark"]["missing_close_dates"], [DAYS[0], DAYS[-1]])
        self.assertEqual(report["containers"]["T01"]["missing_close_dates"], [DAYS[0], DAYS[-1]])
        self.assertFalse(report["research_ready"])

    def test_later_coverage_first_date_cannot_hide_interior_hole(self):
        self.fixture()
        self.mutate("DELETE FROM bars WHERE date=?", (DAYS[2],))
        self.mutate("UPDATE coverage SET first_date=? WHERE theme_id='T01'", (DAYS[3],))
        report = self.report()
        self.assertEqual(report["containers"]["T01"]["first"], DAYS[0])
        self.assertEqual(report["containers"]["T01"]["missing_close_dates"], [DAYS[2]])
        self.assertFalse(report["containers"]["T01"]["research_ready"])

    def test_non_trading_rows_remain_raw_but_do_not_enter_calculation(self):
        days = [d for d in DAYS if d != "2005-01-06"]
        calendar = [d for d in pd.bdate_range("2005-01-04", "2005-01-14").strftime("%Y-%m-%d")
                    if d != "2005-01-06"]
        self.fixture(days=days, calendar=calendar)
        # 一个窗口内工作日休市日与一个周末：只按输入的官方日历筛，不把工作日等同交易日。
        for day in ("2005-01-06", "2005-01-08"):
            self.mutate("INSERT INTO bars VALUES ('H00300', 'raw', ?, NULL, NULL, NULL, 999999, NULL, NULL, 'csi', 'original-time')", (day,))
        before = DB.sha256_file(self.db)
        report = self.report()
        self.assertTrue(report["research_ready"])
        self.assertEqual(report["benchmark"]["excluded_non_trading_dates"], ["2005-01-06", "2005-01-08"])
        self.assertEqual(report["benchmark"]["raw_rows"], len(days) + 2)
        self.assertEqual(report["benchmark"]["view_rows"], len(days))
        pkg = self.package()
        out = B.build(pkg, self.tmp / "panel.sqlite", log=lambda *_: None)
        con = DB.connect(pkg, readonly=True)
        self.assertEqual(con.execute("SELECT close, open, fetched_at FROM bars WHERE date='2005-01-08'").fetchone()[:],
                         (999999, None, "original-time"))
        con.close()
        con = sqlite3.connect(out)
        self.assertEqual(con.execute("SELECT date FROM panel ORDER BY date").fetchall(), [(d,) for d in days])
        self.assertEqual(con.execute("SELECT hs300, hs300_open FROM bench ORDER BY date").fetchall(),
                         [(100.0 + i, 90.0 + i) for i in range(len(days))])
        self.assertEqual(con.execute("SELECT open, high, low, close FROM panel ORDER BY date").fetchall(),
                         [(90.0 + i, 110.0 + i, 80.0 + i, 100.0 + i) for i in range(len(days))])
        con.close()
        built = json.loads(B.report_path(out).read_text())
        self.assertEqual(built["containers"]["沪深300"]["dropped_off_calendar"], 2)
        self.assertEqual(built["containers"]["沪深300"]["ohl_filled_from_close"], 0)
        self.assertEqual(DB.sha256_file(self.db), before)

    def test_null_zero_negative_and_nonfinite_ohlc_fail_closed(self):
        self.fixture()
        for field in ("open", "high", "low", "close"):
            for value in (None, 0.0, -1.0, float("inf"), -float("inf"), float("nan")):
                with self.subTest(field=field, value=value):
                    self.change_bar(DAYS[1], open=91.0, high=111.0, low=81.0, close=101.0)
                    self.change_bar(DAYS[1], **{field: value})
                    report = self.report()
                    self.assertFalse(report["research_ready"])
                    self.assertEqual(report["benchmark_ready"], field != "close")

    def test_missing_calendar_blocks_preflight_and_build(self):
        self.fixture(calendar=[])
        report = self.report()
        self.assertFalse(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertIn("缺官方交易日历", " ".join(report["issues"]))
        self.assert_build_refuses_without_outputs(self.package())

    def test_calendar_missing_head_tail_or_interior_blocks(self):
        calendars = {
            "wrong_year": ["2006-01-03", "2006-01-04"],
            "midyear_head": ["2005-06-01", "2005-06-02"],
            "tail": DAYS[:-1],
            "interior": DAYS + ["2005-02-07"],
        }
        for name, calendar in calendars.items():
            with self.subTest(name=name):
                self.db = self.tmp / f"{name}.sqlite"
                self.fixture(calendar=calendar)
                report = self.report()
                self.assertFalse(report["benchmark_ready"])
                self.assertFalse(report["research_ready"])

    def test_arbitrary_start_must_be_inside_calendar(self):
        self.fixture()
        report = self.report(start=date(2005, 1, 3))
        self.assertFalse(report["benchmark_ready"])
        self.assertIn("覆盖", " ".join(report["issues"]))

    def test_declared_container_without_coverage_is_not_dropped(self):
        self.fixture()
        self.mutate("INSERT INTO universe VALUES (?, ?, ?)",
                    (1, "T99", json.dumps({"theme_id": "T99", "theme": "合成未恢复容器", "status": "retained"})))
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertIn("T99", report["containers"])
        self.assertIn("缺有效研究 coverage", report["containers"]["T99"]["issues"])
        self.assert_build_refuses_without_outputs(self.package())

    def test_error_coverage_is_not_silently_skipped(self):
        self.fixture()
        self.mutate("UPDATE coverage SET error='synthetic failure' WHERE theme_id='T01'")
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertIn("synthetic failure", report["containers"]["T01"]["issues"])
        self.assert_build_refuses_without_outputs(self.package())

    def test_coverage_source_mismatch_blocks_research(self):
        self.fixture()
        self.mutate("UPDATE coverage SET route_used='yahoo' WHERE theme_id='T01'")
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertEqual(report["containers"]["T01"]["source_mismatch_dates"], DAYS[:-1])
        self.assertEqual(report["containers"]["T01"]["unavailable_native_dates"], [DAYS[-1]])

    def test_coverage_cannot_drop_retained_universe_container(self):
        self.fixture()
        self.mutate("UPDATE coverage SET status='execution_only' WHERE theme_id='T01'")
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertIn("T01", report["containers"])

    def test_preflight_cli_reports_json_and_exit_status(self):
        self.fixture()
        argv = ["preflight", "--db", str(self.db), "--end", END.isoformat()]
        for missing_ohl, expected_exit in ((False, 0), (True, 1)):
            with self.subTest(missing_ohl=missing_ohl):
                if missing_ohl:
                    self.change_bar(DAYS[0], open=None)
                before = DB.sha256_file(self.db)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(argv), expected_exit)
                report = json.loads(output.getvalue())
                self.assertTrue(report["benchmark_ready"])
                self.assertEqual(report["research_ready"], not missing_ohl)
                self.assertEqual(DB.sha256_file(self.db), before)

    def test_preflight_missing_db_is_not_created(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["preflight", "--db", str(self.db), "--end", END.isoformat()]), 1)
        self.assertFalse(self.db.exists())

    def test_failed_build_preserves_previous_output(self):
        self.fixture()
        self.change_bar(DAYS[0], open=None)
        pkg = self.package()
        out = self.tmp / "existing-panel.sqlite"
        out.write_bytes(b"previous-panel")
        B.report_path(out).write_bytes(b"previous-report")
        with self.assertRaises(B.BuildError):
            B.build(pkg, out, log=lambda *_: None)
        self.assertEqual(out.read_bytes(), b"previous-panel")
        self.assertEqual(B.report_path(out).read_bytes(), b"previous-report")

    def test_overseas_native_close_only_still_blocks_research(self):
        self.fixture()
        con = DB.connect(self.db)
        run = DB.start_run(con, "backfill")
        DB.write_coverage(con, run, [dict(theme_id="T15", container="合成原油", status="flagged", code="BRENT",
                                         series_code="BRENT", series_adj="raw", route_used="eia", first_date=DAYS[0])])
        DB.finish_run(con, run)
        with con:
            con.execute("INSERT INTO bars VALUES ('BRENT', 'raw', ?, NULL, NULL, NULL, 60, NULL, NULL, 'eia', 'test')", (DAYS[0],))
        con.close()
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertEqual(report["containers"]["T15"]["missing_close_dates"], [])
        self.assertEqual(report["containers"]["T15"]["missing_ohl_dates"], [DAYS[0]])

    def add_overseas(self, native_days, *, missing_ohl_date=None, route="yahoo"):
        cov = dict(theme_id="T99", container="合成海外指数", status="retained", code="SYNTHETIC",
                   series_code="SYNTHETIC", series_adj="raw", route_used=route, first_date=native_days[0],
                   price_only="False")
        con = DB.connect(self.db)
        universe = [json.loads(r[0]) for r in con.execute("SELECT row FROM universe ORDER BY ord")]
        universe.append({"theme_id": cov["theme_id"], "theme": cov["container"], "status": cov["status"]})
        DB.load_universe(con, universe, "synthetic-quality-universe-with-overseas")
        run = DB.start_run(con, "backfill")
        DB.write_coverage(con, run, [cov])
        DB.finish_run(con, run)
        with con:
            con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [("SYNTHETIC", "raw", d, None if d == missing_ohl_date else 99.0 + i,
                              102.0 + i, 98.0 + i, 100.0 + i, 1000.0, None, route, "test")
                             for i, d in enumerate(native_days)])
        con.close()
        return cov

    def add_overseas_warmup(self, *, missing_ohl_date=None):
        native_days = pd.bdate_range("2004-11-01", END.isoformat()).strftime("%Y-%m-%d").tolist()
        cov = self.add_overseas(native_days, missing_ohl_date=missing_ohl_date)
        return cov, native_days

    def test_overseas_only_window_end_bar_blocks_before_build(self):
        for route in ("yahoo", "stooq", "eia"):
            with self.subTest(route=route):
                self.db = self.tmp / f"{route}.sqlite"
                self.fixture()
                self.add_overseas([END.isoformat()], route=route)
                report = self.report()
                self.assertTrue(report["benchmark_ready"])
                self.assertFalse(report["research_ready"])
                overseas = report["containers"]["T99"]
                self.assertFalse(overseas["research_ready"])
                self.assertEqual(overseas["raw_rows"], 1)
                self.assertEqual(overseas["view_rows"], 0)
                self.assertEqual(overseas["alignable_rows"], 0)
                self.assertEqual(overseas["unavailable_native_dates"], [END.isoformat()])
                self.assert_build_refuses_without_outputs(self.package())

    def test_overseas_weekend_end_uses_last_a_share_day_boundary(self):
        self.fixture()
        native_days = ["2005-01-07", "2005-01-08", "2005-01-09"]
        self.add_overseas(native_days)
        end = date(2005, 1, 9)
        report = self.report(end=end)
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        self.assertEqual(report["effective_window"]["last_trading_day"], "2005-01-07")
        self.assertEqual(report["containers"]["T99"]["unavailable_native_dates"], native_days)
        self.assertEqual(report["containers"]["T99"]["alignable_rows"], 0)
        self.assert_build_refuses_without_outputs(self.package(end=end))

    def test_overseas_prior_bar_aligns_and_unused_tail_bad_ohl_does_not_block(self):
        self.fixture()
        self.add_overseas(["2005-01-06", "2005-01-07", "2005-01-10"], missing_ohl_date="2005-01-10")
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertTrue(report["research_ready"])
        overseas = report["containers"]["T99"]
        self.assertEqual(overseas["unavailable_native_dates"], ["2005-01-10"])
        self.assertEqual(overseas["missing_ohl_dates"], [])
        self.assertEqual(overseas["alignable_rows"], 2)
        out = B.build(self.package(), self.tmp / "aligned-panel.sqlite", log=lambda *_: None)
        with sqlite3.connect(out) as con:
            actual = con.execute("SELECT date, close FROM panel WHERE container='合成海外指数' ORDER BY date").fetchall()
        self.assertEqual(actual, [("2005-01-07", 100.0), ("2005-01-10", 101.0)])
        built = json.loads(B.report_path(out).read_text())
        self.assertEqual(built["containers"]["合成海外指数"]["ohl_filled_from_close"], 0)
        self.assertEqual(built["containers"]["合成海外指数"]["last_bar_date"], "2005-01-07")
        # 非交易日 end 的窗口也只消费最后 A 股交易日之前的本地 K 线。
        weekend = self.report(end=date(2005, 1, 9))
        self.assertTrue(weekend["research_ready"])
        self.assertEqual(weekend["containers"]["T99"]["alignable_rows"], 1)
        self.assertEqual(weekend["containers"]["T99"]["unavailable_native_dates"], ["2005-01-07"])
        weekend_out = B.build(self.package(end=date(2005, 1, 9)), self.tmp / "weekend-panel.sqlite", log=lambda *_: None)
        with sqlite3.connect(weekend_out) as con:
            self.assertEqual(con.execute("SELECT date, close FROM panel WHERE container='合成海外指数'").fetchall(),
                             [("2005-01-07", 100.0)])

    def test_prewindow_overseas_bar_keeps_existing_stale_and_hole_rules(self):
        calendar = pd.bdate_range("2005-01-04", "2005-01-18").strftime("%Y-%m-%d").tolist()
        days = [d for d in calendar if d <= "2005-01-14"]
        self.fixture(days=days, calendar=calendar)
        self.add_overseas(["2004-12-31"])
        end = date(2005, 1, 14)
        report = self.report(end=end)
        self.assertTrue(report["research_ready"])
        self.assertEqual(report["containers"]["T99"]["alignable_rows"], len(days))
        self.assertEqual(report["containers"]["T99"]["native_warmup_rows"], 1)
        out = B.build(self.package(end=end), self.tmp / "stale-panel.sqlite", log=lambda *_: None)
        with sqlite3.connect(out) as con:
            actual = con.execute("SELECT date, close, data_hole FROM panel WHERE container='合成海外指数' ORDER BY date").fetchall()
        self.assertEqual(actual, [(d, 100.0, int(i >= B.HOLE_MIN)) for i, d in enumerate(days)])
        built = json.loads(B.report_path(out).read_text())["containers"]["合成海外指数"]
        self.assertEqual(built["stale_days"], len(days) - 1)
        self.assertEqual(built["data_hole_rows"], len(days) - B.HOLE_MIN)
        self.assertEqual(built["last_bar_date"], "2004-12-31")

    def test_strict_overseas_preserves_pre2005_native_indicator_warmup(self):
        self.fixture()
        cov, native_days = self.add_overseas_warmup()
        con = DB.connect(self.db, readonly=True)
        try:
            cal = pd.DatetimeIndex(DAYS)
            strict, _ = B.research_frame(con, cov, cal, strict=True)
            legacy, _ = B.research_frame(con, cov, cal, strict=False)
        finally:
            con.close()
        pd.testing.assert_frame_equal(strict[["date", "atr20", "state"]], legacy[["date", "atr20", "state"]])
        self.assertTrue(strict["atr20"].notna().all(), "窗口第一日已由海外原生历史预热")
        self.assertIn("TREND_UP", strict["state"].tolist())
        report = self.report()
        self.assertTrue(report["research_ready"])
        self.assertEqual(report["containers"]["T99"]["native_warmup_rows"], sum(d < DAYS[0] for d in native_days))

    def test_missing_pre2005_native_ohl_blocks_preflight(self):
        self.fixture()
        missing = "2004-12-15"
        _, native_days = self.add_overseas_warmup(missing_ohl_date=missing)
        report = self.report()
        self.assertTrue(report["benchmark_ready"])
        self.assertFalse(report["research_ready"])
        overseas = report["containers"]["T99"]
        self.assertFalse(overseas["research_ready"])
        self.assertEqual(overseas["missing_ohl_dates"], [missing])
        self.assertEqual(overseas["native_warmup_rows"], sum(d < DAYS[0] for d in native_days))
        self.assertIn("策略缺真实 OHLC", " ".join(overseas["issues"]))


if __name__ == "__main__":
    unittest.main()
