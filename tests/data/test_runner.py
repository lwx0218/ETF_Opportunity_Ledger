"""probe / backfill / update / calendar / package / verify / compare，读写临时的 market.sqlite。假网络，不出网。"""
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import db as DB, http, runner, store     # noqa: E402
from src.data import __main__ as data_cli              # noqa: E402
from tests.data.fakenet import FakeNet                  # noqa: E402

END = date(2026, 9, 30)
START = date(2000, 1, 1)


def read_cov(db):
    con = DB.connect(db, readonly=True)
    try:
        return {r["theme_id"]: r for r in DB.read_coverage(con)}
    finally:
        con.close()


def series_rows(db, code, adj):
    con = DB.connect(db, readonly=True)
    try:
        return store.read(con, code, adj)
    finally:
        con.close()


def query(db, sql, *args):
    con = DB.connect(db, readonly=True)
    try:
        return [tuple(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def rmtree(path):
    for p in Path(path).rglob("*"):                    # 数据包是只读文件：删之前放开权限
        if p.is_file():
            p.chmod(stat.S_IWUSR | stat.S_IRUSR)
    shutil.rmtree(path)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(rmtree, self.tmp)
        self.db = self.tmp / "market.sqlite"
        self.net = FakeNet()
        self.clock = mock.patch("src.data.runner._utcnow", return_value=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
        for p in (mock.patch.object(http, "get", side_effect=self.get), mock.patch("src.data.sources.time.sleep"), self.clock):
            p.start()
            self.addCleanup(p.stop)
        self.log = []

    def get(self, url, params=None, **kw):
        """假网络 + 与 http.get 相同的请求记录（runner 把 http.LOG 写进 requests 表）。"""
        try:
            raw = self.net.get(url, params, **kw)
        except http.FetchError as e:
            http.LOG.append({"url": url, "fetched_at": "2026-10-01T12:00:00+00:00", "bytes": None, "sha256": None, "error": str(e)[:80]})
            raise
        http.LOG.append({"url": url, "fetched_at": "2026-10-01T12:00:00+00:00", "bytes": len(raw), "sha256": "x", "error": None})
        return raw

    def probe(self, **kw):
        return runner.probe(END, start=START, db=self.db, log=self.log.append, **kw)

    def backfill(self, **kw):
        return runner.backfill(END, start=START, db=self.db, log=self.log.append, **kw)

    def update(self, **kw):
        return runner.update(END, db=self.db, log=self.log.append, **kw)

    def package(self, end, **kw):
        return runner.package(end, db=self.db, pkg_root=self.tmp / "pkg", log=self.log.append, **kw)


class Probe(Base):
    def test_everything_blocked_still_writes_one_row_per_container(self):
        self.probe()
        cov = read_cov(self.db)
        self.assertEqual(len(cov), 39)
        panel = [c for c in cov.values() if c["status"] in ("retained", "flagged")]
        self.assertEqual(len(panel), 37)
        for c in panel:                         # 完成判据：每个面板容器有 route_used 或明确 error
            self.assertTrue(c["route_used"] or c["error"], c["theme_id"])
            self.assertTrue(c["error"], c["theme_id"])
        self.assertEqual(cov["T29"]["error"], "")
        self.assertIn("剔除", cov["T29"]["notes"])
        self.assertIn("只作执行", cov["T34"]["notes"])
        self.assertTrue(cov["T34"]["exec_error"])
        self.assertIn("EIA_API_KEY", cov["T15"]["error"])
        reqs = query(self.db, "SELECT r.kind, count(q.seq) FROM runs r JOIN requests q USING (run_id) GROUP BY r.run_id")
        self.assertEqual(reqs[0][0], "probe")
        self.assertGreater(reqs[0][1], 39)                                       # 每个请求一条记录（取代 probe-requests.jsonl）

    def test_total_return_adopted(self):
        self.net.add("csi", "000300", "沪深300指数", "2004-12-31", "2026-09-29")
        self.net.add("csi", "H00300", "沪深300全收益指数", "2004-12-31", "2026-09-29", base=1000)
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-29")
        self.probe(only=["T01"])
        c = read_cov(self.db)["T01"]
        self.assertEqual((c["route_used"], c["tr_code_used"], c["price_only"], c["series_adj"]), ("csi", "H00300", "False", "raw"))
        self.assertEqual((c["first_date"], c["last_date"], c["error"]), ("2004-12-31", "2026-09-29", ""))
        self.assertEqual((c["exec_route"], c["exec_last_date"], c["exec_first_date"]), ("eastmoney_etf", "2026-09-29", ""))
        self.assertNotIn("csi:000300", self.net.calls)      # probe 有全收益时不再拉价格序列

    def test_tr_candidate_without_marker_rejected(self):
        self.net.add("csi", "000688", "上证科创板50成份指数", "2019-12-31", "2026-09-29")
        self.net.add("csi", "H00688", "上证科创板50成份指数", "2019-12-31", "2026-09-29")       # 名称无全收益标记
        self.net.add("csi", "000688CNY010", "上证科创板50成份全收益指数", "2019-12-31", "2026-09-29")
        self.probe(only=["T04"])
        c = read_cov(self.db)["T04"]
        self.assertEqual(c["tr_code_used"], "000688CNY010")
        self.assertIn("H00688", c["notes"])

    def test_price_only_when_no_tr(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-29")
        self.probe(only=["T02"])
        c = read_cov(self.db)["T02"]
        self.assertEqual((c["route_used"], c["tr_code_used"], c["price_only"], c["series_code"]), ("csi", "", "True", "000905"))
        self.assertIn("H00905", c["notes"])

    def test_declared_fallback_for_treasury(self):
        self.net.add("csi", "H11077", "中证10年期国债指数", "2008-12-31", "2026-09-29")
        self.net.add("em", "1.511260:2", "十年国债ETF", "2017-08-24", "2026-09-29")
        self.probe(only=["T33"])
        c = read_cov(self.db)["T33"]
        self.assertEqual((c["series_code"], c["route_used"], c["series_adj"], c["price_only"]),
                         ("511260", "eastmoney_etf_hfq", "hfq", "False"))
        self.assertIn("replan §1", c["notes"])

    def test_approximate_index_never_adopted(self):
        self.net.add("yahoo", "^NDXT", "NASDAQ-100 Technology Sector", "2006-02-22", "2026-09-29")
        self.probe(only=["T36"])
        c = read_cov(self.db)["T36"]
        self.assertEqual(c["route_used"], "")
        self.assertTrue(c["error"])
        self.assertIn("^NDXT 可得；未自动采用", c["notes"])

    def test_eastmoney_index_falls_back_to_tencent(self):
        self.net.add("tencent", "sz399006", "创业板指", "2010-06-01", "2026-09-29")
        self.probe(only=["T05"])
        c = read_cov(self.db)["T05"]
        self.assertEqual((c["route_used"], c["price_only"]), ("tencent_index", "True"))
        self.assertIn("前序路由失败：eastmoney_index", c["notes"])

    def test_commodity_is_not_price_only(self):
        self.net.add("yahoo", "BZ=F", "Brent Crude Oil", "2007-07-30", "2026-09-29")
        self.probe(only=["T15"])
        c = read_cov(self.db)["T15"]
        self.assertEqual((c["route_used"], c["series_code"], c["series_adj"], c["price_only"]), ("yahoo", "BRENT", "raw", "n/a"))
        self.assertIn("EIA_API_KEY", c["notes"])
        self.assertEqual(c["ohlc_missing_rows"], "0")

    def test_gap_is_flagged(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-29")
        rows = self.net.csi["000905"][1]
        rows[:] = [(d, c) for d, c in rows if not ("2010-03-01" <= d <= "2010-05-31")]
        self.probe(only=["T02"])
        c = read_cov(self.db)["T02"]
        self.assertIn("最大间隔", c["notes"])
        self.assertGreater(int(c["max_gap_days"]), 90)

    def test_series_that_stopped_is_an_error(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2012-06-29")      # 之后整年为空 = 停更
        self.probe(only=["T02"])
        c = read_cov(self.db)["T02"]
        self.assertEqual(c["route_used"], "")
        self.assertIn("空段", c["error"])

    def test_intraday_bar_is_dropped(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-29")
        noon = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)                       # 北京 12:00，未收盘
        with mock.patch("src.data.runner._utcnow", return_value=noon):
            self.probe(only=["T02"])
        c = read_cov(self.db)["T02"]
        self.assertEqual(c["last_date"], "2026-09-28")
        self.assertIn("丢弃未收盘 K 线 1 行", c["notes"])

    def test_only_keeps_other_rows(self):
        self.probe()
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-29")
        self.probe(only=["T02"])
        cov = read_cov(self.db)
        self.assertEqual(len(cov), 39)
        self.assertEqual(cov["T02"]["route_used"], "csi")
        self.assertEqual(list(cov)[:3], ["T01", "T02", "T03"])
        runs = query(self.db, "SELECT kind, status FROM runs ORDER BY run_id")
        self.assertEqual(runs, [("probe", "ok"), ("probe", "ok")])
        self.assertEqual(query(self.db, "SELECT count(*) FROM coverage"), [(40,)])           # 历史保留：第二次只写了 T02
        self.assertEqual(query(self.db, "SELECT count(*) FROM bars"), [(0,)])                # probe 不落行情


class BackfillUpdatePackage(Base):
    def setUp(self):
        super().setUp()
        self.net.add("csi", "000300", "沪深300指数", "2004-12-31", "2026-09-25")
        self.net.add("csi", "H00300", "沪深300全收益指数", "2004-12-31", "2026-09-25", base=1000)
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-25")
        self.net.add("em", "1.518880:2", "黄金ETF", "2013-07-29", "2026-09-25")
        self.net.add("em", "1.518880:0", "黄金ETF", "2013-07-29", "2026-09-25", base=3)

    def test_exec_start_only_shortens_execution_series(self):
        self.backfill(exec_start=date(2020, 1, 1), only=["T01"])
        c = read_cov(self.db)["T01"]
        self.assertEqual((c["first_date"], c["exec_first_date"]), ("2004-12-31", "2020-01-01"))

    def test_backfill_writes_all_series(self):
        self.backfill(only=["T01", "T16"])
        self.assertEqual(query(self.db, "SELECT DISTINCT code, adj, source FROM bars ORDER BY code, adj"),
                         [("000300", "raw", "csi"), ("510300", "raw", "eastmoney_etf"), ("518880", "hfq", "eastmoney_etf_hfq"),
                          ("518880", "raw", "eastmoney_etf"), ("H00300", "raw", "csi")])
        c = read_cov(self.db)["T16"]
        self.assertEqual((c["series_code"], c["series_adj"], c["price_only"], c["exec_first_date"]), ("518880", "hfq", "False", "2013-07-29"))
        self.assertIn("Au99.99", c["notes"])
        self.assertEqual(query(self.db, "SELECT kind, status, end_date FROM runs"), [("backfill", "ok", "2026-09-30")])
        self.assertEqual(query(self.db, "SELECT value FROM meta WHERE key = 'universe_sha256'"), [(DB.sha256_file(ROOT / "data" / "universe.csv"),)])
        self.assertEqual(query(self.db, "PRAGMA journal_mode"), [("delete",)])
        self.assertFalse(any(self.tmp.glob("market.sqlite-*")))                  # 入 Git 的库不留 -wal / -shm / -journal

    def test_backfill_again_replaces_series(self):
        self.backfill(only=["T01"])
        self.net.csi["000300"][1][:] = self.net.csi["000300"][1][:-5]           # 第二次全量少 5 天：整条替换，不残留旧行
        self.backfill(only=["T01"])
        self.assertEqual(series_rows(self.db, "000300", "raw")[-1]["date"], "2026-09-18")

    def test_update_overlaps_and_counts_revisions(self):
        self.backfill(only=["T01"])
        for code in ("H00300", "000300"):
            name, rows = self.net.csi[code]
            rows += [("2026-09-28", 9999.0), ("2026-09-29", 9999.5)]
        rows = self.net.csi["000300"][1]                                    # 价格序列：重叠区修正照常合并并计数
        i = next(k for k, (d, _) in enumerate(rows) if d == "2026-09-24")
        rows[i] = ("2026-09-24", 1.0)
        before = {r["date"]: r for r in series_rows(self.db, "000300", "raw")}
        rep = self.update(only=["T01"])
        px = next(r for r in rep if r["code"] == "000300")
        self.assertEqual((px["added"], px["revised"], px["since"]), (2, 1, "2026-09-15"))
        tr = next(r for r in rep if r["code"] == "H00300")
        self.assertEqual((tr["added"], tr["revised"]), (2, 0))
        self.assertEqual(read_cov(self.db)["T01"]["last_date"], "2026-09-29")
        after = {r["date"]: r for r in series_rows(self.db, "000300", "raw")}
        self.assertEqual(after["2026-09-24"]["close"], 1.0)
        self.assertEqual(after["2026-09-01"], before["2026-09-01"])                  # 重叠区之前的行不动
        res = query(self.db, "SELECT code, adj, route, ok, added, revised FROM update_results ORDER BY seq")
        self.assertIn(("000300", "raw", "csi", 1, 2, 1), res)                         # 取代 update-log.jsonl
        self.assertEqual(query(self.db, "SELECT kind FROM runs ORDER BY run_id"), [("backfill",), ("update",)])
        self.assertTrue(query(self.db, "SELECT 1 FROM requests JOIN runs USING (run_id) WHERE kind = 'update'"))

    def test_update_refuses_rebased_total_return(self):
        self.backfill(only=["T01"])
        before = series_rows(self.db, "H00300", "raw")
        rows = self.net.csi["H00300"][1]
        i = next(k for k, (d, _) in enumerate(rows) if d == "2026-09-24")
        rows[i] = ("2026-09-24", 1.0)
        rep = self.update(only=["T01"])
        tr = next(r for r in rep if r["code"] == "H00300")
        self.assertFalse(tr["ok"])
        self.assertIn("重新全量 backfill", tr["error"])
        self.assertEqual(series_rows(self.db, "H00300", "raw"), before)

    def test_update_failure_keeps_old_data(self):
        self.backfill(only=["T01"])
        before = series_rows(self.db, "H00300", "raw")
        del self.net.csi["H00300"]
        rep = self.update(only=["T01"])
        self.assertFalse(next(r for r in rep if r["code"] == "H00300")["ok"])
        self.assertEqual(series_rows(self.db, "H00300", "raw"), before)

    def test_update_without_backfill_refused_and_recorded(self):
        with self.assertRaisesRegex(SystemExit, "先跑 backfill"):
            self.update()
        self.assertEqual(query(self.db, "SELECT kind, substr(status, 1, 5) FROM runs"), [("update", "error")])

    def test_package_truncates_and_verifies(self):
        self.backfill(only=["T01", "T16"])
        src_sha = DB.sha256_file(self.db)
        dest = self.package(date(2026, 9, 18))
        self.assertEqual(dest.name, "research-package-2026-09-18.sqlite")
        self.assertEqual(DB.sha256_file(self.db), src_sha)                      # 只读源库：本地打包不改动入 Git 的库
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o444)               # 包是只读文件
        self.assertEqual(series_rows(dest, "H00300", "raw")[-1]["date"], "2026-09-18")
        cov = read_cov(dest)
        self.assertEqual((cov["T01"]["last_date"], cov["T01"]["exec_last_date"]), ("2026-09-18", "2026-09-18"))
        meta = json.loads(runner.manifest_path(dest).read_text(encoding="utf-8"))
        self.assertEqual((meta["series"], meta["end"], meta["source_db_sha256"], meta["file"]), (5, "2026-09-18", src_sha, dest.name))
        self.assertEqual(meta["sha256"], DB.sha256_file(dest))
        con = DB.connect(dest, readonly=True)
        info = runner.package_info(con)
        con.close()
        self.assertEqual((info["end"], info["source_db_sha256"], info["series"], info["inconsistent_with_bars"]),
                         ("2026-09-18", src_sha, 5, []))
        self.assertEqual(query(dest, "SELECT kind, status FROM runs"), [("package", "ok")])
        self.assertEqual(runner.verify(dest), [])
        with mock.patch("builtins.print"):
            self.assertEqual(data_cli.main(["verify", str(dest)]), 0)

    def _tamper(self, dest, sql, manifest=True):
        """改一处包内数据；manifest=True 时顺手把 MANIFEST 的 sha256 也改成新文件的（只剩内容层面的检查能发现）。"""
        dest.chmod(0o644)
        con = sqlite3.connect(dest)
        con.executescript(sql)
        con.commit()
        con.close()
        if manifest:
            man = runner.manifest_path(dest)
            m = json.loads(man.read_text(encoding="utf-8"))
            man.write_text(json.dumps({**m, "sha256": DB.sha256_file(dest)}), encoding="utf-8")

    def test_verify_catches_each_problem(self):
        self.backfill(only=["T01", "T16"])
        end = date(2026, 9, 18)
        cases = {
            "哈希不符": ("UPDATE bars SET close = close + 1 WHERE code = 'H00300' AND date = '2026-09-18'", False),
            "晚于 end": ("INSERT INTO bars VALUES ('H00300', 'raw', '2026-09-21', 1, 1, 1, 1, NULL, NULL, 'csi', 'x');"
                         "UPDATE coverage SET rows = rows + 1 WHERE theme_id = 'T01'", True),
            "行数不符": ("DELETE FROM bars WHERE code = '510300' AND date = '2026-09-01'", True),
            "来源不符": ("UPDATE coverage SET route_used = 'eastmoney_index' WHERE theme_id = 'T01'", True),
            "清单外序列": ("INSERT INTO bars VALUES ('XYZ', 'raw', '2026-09-01', 1, 1, 1, 1, NULL, NULL, 'csi', 'x')", True),
        }
        for want, (sql, manifest) in cases.items():
            with self.subTest(want):
                dest = self.package(end, force=True)
                self.assertEqual(runner.verify(dest), [])
                self._tamper(dest, sql, manifest=manifest)
                problems = runner.verify(dest)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(want, problems[0])
        dest = self.package(end, force=True)
        runner.manifest_path(dest).unlink()
        self.assertIn("缺 research-package-2026-09-18.MANIFEST.json", runner.verify(dest))
        dest.chmod(0o644)
        dest.write_bytes(b"not a database" * 100)
        self.assertTrue(any("打不开" in x for x in runner.verify(dest)))

    def test_package_marks_coverage_bars_mismatch_as_error(self):
        self.backfill(only=["T01", "T16"])
        cov = read_cov(self.db)
        # 模拟 backfill 之后又跑 probe：T02 在 coverage 里有路由，但库里没有这条序列
        con = DB.connect(self.db)
        run = DB.start_run(con, "probe", end=END)
        DB.write_coverage(con, run, [dict(cov["T01"], theme_id="T02", container="中证500", series_code="H00905", series_adj="raw")])
        store.replace(con, "STALE", "csi", [{"date": "2026-09-01", "close": 1.0}], "x")
        con.close()
        dest = self.package(date(2026, 9, 18))
        pc = read_cov(dest)
        self.assertEqual((pc["T02"]["route_used"], pc["T02"]["series_adj"]), ("", ""))
        self.assertIn("coverage 与 bars 不一致", pc["T02"]["error"])
        meta = json.loads(runner.manifest_path(dest).read_text(encoding="utf-8"))
        self.assertEqual((meta["with_series"], meta["inconsistent_with_bars"]), (2, ["T02"]))
        self.assertFalse(series_rows(dest, "STALE", "raw"))                      # coverage 没引用的序列不进包
        self.assertEqual(runner.verify(dest), [])

    def test_package_carries_calendar(self):
        self.backfill(only=["T01"])
        cal = self.tmp / "days.csv"
        cal.write_text("date\n" + "\n".join(d.isoformat() for d in (date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30),
                                                                      date(2026, 10, 9))) + "\n", encoding="utf-8")
        self.assertEqual(runner.load_calendar(cal, db=self.db, log=self.log.append), 4)
        dest = self.package(date(2026, 9, 18))
        self.assertEqual(query(dest, "SELECT count(*) FROM calendar"), [(4,)])
        meta = json.loads(runner.manifest_path(dest).read_text(encoding="utf-8"))
        self.assertEqual(meta["calendar_days"], 4)

    def test_package_refuses_unclosed_end(self):
        self.backfill(only=["T01"])
        us_not_closed = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)   # 北京 20:00，纽约 08:00
        with mock.patch("src.data.runner._utcnow", return_value=us_not_closed):
            with self.assertRaisesRegex(SystemExit, "尚未全部收盘"):
                self.package(date(2026, 9, 30))

    def test_package_refuses_to_overwrite(self):
        self.backfill(only=["T01"])
        self.package(END)
        with self.assertRaises(SystemExit):
            self.package(END)
        dest = self.package(END, force=True)
        self.assertEqual(runner.verify(dest), [])


class Calendar(Base):
    def test_load_union_and_refusals(self):
        f = self.tmp / "a.csv"
        f.write_text("\ufefftrade_date\n2026-09-29\n20260930\n2026-10-08\n", encoding="utf-8")
        self.assertEqual(runner.load_calendar(f, db=self.db, log=self.log.append), 3)
        g = self.tmp / "b.csv"
        g.write_text("2026-10-09\n2026-10-12\n", encoding="utf-8")
        self.assertEqual(runner.load_calendar(g, db=self.db, log=self.log.append), 5)              # 每年补一次：取并集
        bad = {"two_columns": "date,jybz\n2026-10-30,1\n", "weekend": "2026-10-31\n", "gap": "2026-12-15\n",   # 并入后缺一段
               "junk": "date\n2026-10-14\nxx\n"}
        for k, text in bad.items():
            (self.tmp / f"{k}.csv").write_text(text, encoding="utf-8")
            with self.subTest(k), self.assertRaises(SystemExit):
                runner.load_calendar(self.tmp / f"{k}.csv", db=self.db, log=self.log.append)
        self.assertEqual(query(self.db, "SELECT count(*) FROM calendar"), [(5,)])                  # 拒绝时库不动
        self.assertEqual(runner.load_calendar(g, replace=True, db=self.db, log=self.log.append), 2)
        self.assertEqual(query(self.db, "SELECT kind FROM runs WHERE status = 'ok'"), [("calendar",)] * 3)


class Schema(unittest.TestCase):
    """库表约束：主键、adj 取值、hfq 只给后复权路由、一条序列只来自一个路由、默认库在测试里连不上。"""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.con = DB.connect(self.tmp / "m.sqlite")
        self.addCleanup(self.con.close)

    def ins(self, code="510300", adj="raw", d="2026-09-01", source="eastmoney_etf"):
        with self.con:
            self.con.execute("INSERT INTO bars VALUES (?, ?, ?, 1, 1, 1, 1, NULL, NULL, ?, 'x')", (code, adj, d, source))

    def test_bars_constraints(self):
        self.ins()
        with self.assertRaises(sqlite3.IntegrityError):
            self.ins()                                                           # 主键 (code, adj, date)
        for kw in ({"adj": "qfq"}, {"adj": "hfq"}, {"adj": "raw", "source": "eastmoney_etf_hfq"}, {"d": "2026-9-1"}, {"d": "2026-02-30"},
                   {"source": ""}, {"code": ""}):
            with self.subTest(kw), self.assertRaises(sqlite3.IntegrityError):
                self.ins(**{"d": "2026-09-02", **kw})
        with self.assertRaisesRegex(sqlite3.IntegrityError, "只来自一个路由"):
            self.ins(d="2026-09-02", source="tencent_etf")                        # 同一序列换来源：拒绝拼接
        self.ins(adj="hfq", source="eastmoney_etf_hfq")                           # 同一代码的后复权是另一条序列
        with self.assertRaises(store.MixError):
            store.merge(store.read(self.con, "510300", "raw"), [{"date": "2026-09-03", "close": 2.0}], "tencent_etf")

    def test_calendar_rejects_weekends_and_bad_dates(self):
        for d in ("2026-10-03", "2026-10-04", "20261009", "2026-13-01"):
            with self.subTest(d), self.assertRaises(sqlite3.IntegrityError), self.con:
                self.con.execute("INSERT INTO calendar VALUES (?)", (d,))

    def test_old_or_foreign_schema_refused(self):
        self.con.execute("UPDATE meta SET value = 'market-v0' WHERE key = 'schema'")
        self.con.commit()
        with self.assertRaisesRegex(DB.DbError, "需迁移"):
            DB.connect(self.tmp / "m.sqlite")
        with self.assertRaisesRegex(DB.DbError, "需迁移"):
            DB.connect(self.tmp / "m.sqlite", readonly=True)

    def test_default_db_refused_in_tests(self):
        self.assertEqual(os.environ.get(DB.TESTING_ENV), "1")
        existed = {p: p.exists() for p in (DB.MARKET_DB, ROOT / "data" / "ledger.sqlite")}
        for fn in (lambda: DB.connect(), lambda: DB.connect(DB.MARKET_DB, readonly=True),
                   lambda: runner.probe(END, log=lambda *_: None), lambda: runner.package(END, pkg_root=self.tmp),
                   lambda: DB.connect(ROOT / "data" / ".." / "data" / "market.sqlite")):
            with self.assertRaisesRegex(DB.DbError, "临时库"):
                fn()
        from src.indicators.calendar import load_trading_days
        from src.ledger.store import DEFAULT_DB, Ledger, LedgerError
        with self.assertRaisesRegex(DB.DbError, "临时库"):
            load_trading_days()
        with self.assertRaisesRegex(LedgerError, "临时库"):
            Ledger(DEFAULT_DB)
        self.assertEqual({p: p.exists() for p in existed}, existed)              # 拒绝发生在建文件之前


class Store(unittest.TestCase):
    def test_merge_refuses_other_source(self):
        old = [{"date": "2026-09-24", "close": 1.0, "source": "eia"}]
        with self.assertRaises(store.MixError):
            store.merge(old, [{"date": "2026-09-25", "close": 2.0}], "yahoo")

    def test_adj(self):
        self.assertEqual(store.adj_of("eastmoney_etf_hfq"), "hfq")
        self.assertEqual({store.adj_of(r) for r in ("csi", "yahoo", "eia", "eastmoney_etf", "tencent_etf")}, {"raw"})


class Compare(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.db = self.tmp / "m.sqlite"

    def put(self, raw, ref):
        con = DB.connect(self.db)
        store.replace(con, "510300", "eastmoney_etf", [{"date": d, "close": c} for d, c in raw], "x")
        con.close()
        (self.tmp / "ref.csv").write_text("date,close\n" + "".join(f"{d},{c}\n" for d, c in ref), encoding="utf-8")

    def test_rounding_noise_is_not_a_step(self):
        raw = [(f"2026-06-{d:02d}", round(3.0 + d * 0.0137, 3)) for d in range(1, 21)]
        self.put(raw, [(d, round(c - (0.0725 if d < "2026-06-15" else 0), 3)) for d, c in raw])
        res = runner.compare(self.tmp / "ref.csv", "510300", db=self.db)
        self.assertEqual([s["date"] for s in res["steps"]], ["2026-06-15"])

    def test_subtractive_qfq_steps(self):
        raw = [("2026-06-01", 3.0), ("2026-06-02", 3.1), ("2026-06-03", 3.0), ("2026-06-04", 3.05)]
        div = {"2026-06-01": 0.1, "2026-06-02": 0.1}           # 06-03 除息 0.1：此前 qfq = raw − 0.1
        self.put(raw, [(d, round(c - div.get(d, 0), 4)) for d, c in raw])
        res = runner.compare(self.tmp / "ref.csv", "510300", db=self.db, out=self.tmp / "diff.csv")
        self.assertEqual((res["overlap"], res["equal"]), (4, 2))
        self.assertEqual([s["date"] for s in res["steps"]], ["2026-06-03"])
        self.assertTrue((self.tmp / "diff.csv").exists())


if __name__ == "__main__":
    unittest.main()
