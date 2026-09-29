"""probe / backfill / update / package / verify / compare。假网络，不出网。"""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import http, runner, store         # noqa: E402
from tests.data.fakenet import FakeNet            # noqa: E402

END = date(2026, 9, 30)
START = date(2000, 1, 1)


def read_cov(path):
    with open(path, encoding="utf-8") as f:
        return {r["theme_id"]: r for r in csv.DictReader(f)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.raw, self.out = self.tmp / "raw", self.tmp / "out"
        self.net = FakeNet()
        for p in (mock.patch.object(http, "get", side_effect=self.net.get), mock.patch("src.data.sources.time.sleep")):
            p.start()
            self.addCleanup(p.stop)
        self.log = []

    def probe(self, **kw):
        return runner.probe(END, start=START, out_dir=self.out, log=self.log.append, **kw)

    def backfill(self, **kw):
        return runner.backfill(END, start=START, raw_dir=self.raw, out_dir=self.out, log=self.log.append, **kw)


class Probe(Base):
    def test_everything_blocked_still_writes_one_row_per_container(self):
        self.probe()
        cov = read_cov(self.out / "coverage.csv")
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
        self.assertTrue((self.out / "probe-requests.jsonl").exists())

    def test_total_return_adopted(self):
        self.net.add("csi", "000300", "沪深300指数", "2004-12-31", "2026-09-29")
        self.net.add("csi", "H00300", "沪深300全收益指数", "2004-12-31", "2026-09-29", base=1000)
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-29")
        self.probe(only=["T01"])
        c = read_cov(self.out / "coverage.csv")["T01"]
        self.assertEqual((c["route_used"], c["tr_code_used"], c["price_only"], c["series_file"]), ("csi", "H00300", "False", "H00300.csv"))
        self.assertEqual((c["first_date"], c["last_date"], c["error"]), ("2004-12-31", "2026-09-29", ""))
        self.assertEqual((c["exec_route"], c["exec_last_date"], c["exec_first_date"]), ("eastmoney_etf", "2026-09-29", ""))
        self.assertNotIn("csi:000300", self.net.calls)      # probe 有全收益时不再拉价格序列

    def test_tr_candidate_without_marker_rejected(self):
        self.net.add("csi", "000688", "上证科创板50成份指数", "2019-12-31", "2026-09-29")
        self.net.add("csi", "H00688", "上证科创板50成份指数", "2019-12-31", "2026-09-29")       # 名称无全收益标记
        self.net.add("csi", "000688CNY010", "上证科创板50成份全收益指数", "2019-12-31", "2026-09-29")
        self.probe(only=["T04"])
        c = read_cov(self.out / "coverage.csv")["T04"]
        self.assertEqual(c["tr_code_used"], "000688CNY010")
        self.assertIn("H00688", c["notes"])

    def test_price_only_when_no_tr(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-29")
        self.probe(only=["T02"])
        c = read_cov(self.out / "coverage.csv")["T02"]
        self.assertEqual((c["route_used"], c["tr_code_used"], c["price_only"], c["series_code"]), ("csi", "", "True", "000905"))
        self.assertIn("H00905", c["notes"])

    def test_declared_fallback_for_treasury(self):
        self.net.add("csi", "H11077", "中证10年期国债指数", "2008-12-31", "2026-09-29")
        self.net.add("em", "1.511260:2", "十年国债ETF", "2017-08-24", "2026-09-29")
        self.probe(only=["T33"])
        c = read_cov(self.out / "coverage.csv")["T33"]
        self.assertEqual((c["series_code"], c["route_used"], c["series_file"], c["price_only"]),
                         ("511260", "eastmoney_etf_hfq", "511260.hfq.csv", "False"))
        self.assertIn("replan §1", c["notes"])

    def test_approximate_index_never_adopted(self):
        self.net.add("yahoo", "^NDXT", "NASDAQ-100 Technology Sector", "2006-02-22", "2026-09-29")
        self.probe(only=["T36"])
        c = read_cov(self.out / "coverage.csv")["T36"]
        self.assertEqual(c["route_used"], "")
        self.assertTrue(c["error"])
        self.assertIn("^NDXT 可得；未自动采用", c["notes"])

    def test_eastmoney_index_falls_back_to_tencent(self):
        self.net.add("tencent", "sz399006", "创业板指", "2010-06-01", "2026-09-29")
        self.probe(only=["T05"])
        c = read_cov(self.out / "coverage.csv")["T05"]
        self.assertEqual((c["route_used"], c["price_only"]), ("tencent_index", "True"))
        self.assertIn("前序路由失败：eastmoney_index", c["notes"])

    def test_gap_is_flagged(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2010-01-01")
        self.net.csi["000905"][1].extend([("2010-03-01", 5.0), ("2010-03-02", 5.1)])
        self.probe(only=["T02"])
        self.assertIn("最大间隔", read_cov(self.out / "coverage.csv")["T02"]["notes"])

    def test_only_keeps_other_rows(self):
        self.probe()
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-29")
        self.probe(only=["T02"])
        cov = read_cov(self.out / "coverage.csv")
        self.assertEqual(len(cov), 39)
        self.assertEqual(cov["T02"]["route_used"], "csi")
        self.assertEqual(list(cov)[:3], ["T01", "T02", "T03"])


class BackfillUpdatePackage(Base):
    def setUp(self):
        super().setUp()
        self.net.add("csi", "000300", "沪深300指数", "2004-12-31", "2026-09-25")
        self.net.add("csi", "H00300", "沪深300全收益指数", "2004-12-31", "2026-09-25", base=1000)
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-25")
        self.net.add("em", "1.518880:2", "黄金ETF", "2013-07-29", "2026-09-25")
        self.net.add("em", "1.518880:0", "黄金ETF", "2013-07-29", "2026-09-25", base=3)

    def test_backfill_writes_all_series(self):
        self.backfill(only=["T01", "T16"])
        self.assertEqual(sorted(p.name for p in self.raw.glob("*.csv")), ["000300.csv", "510300.csv", "518880.csv", "518880.hfq.csv", "H00300.csv"])
        rows = store.read(self.raw / "518880.hfq.csv")
        self.assertEqual({r["source"] for r in rows}, {"eastmoney_etf_hfq"})
        c = read_cov(self.out / "coverage.csv")["T16"]
        self.assertEqual((c["series_file"], c["price_only"], c["exec_first_date"]), ("518880.hfq.csv", "False", "2013-07-29"))
        self.assertIn("Au99.99", c["notes"])

    def test_update_overlaps_and_counts_revisions(self):
        self.backfill(only=["T01"])
        self.net.csi["H00300"] = ("沪深300全收益指数", self.net.csi["H00300"][1] + [("2026-09-28", 9999.0), ("2026-09-29", 9999.5)])
        # 修正 09-24 的值：应计入 revised
        rows = self.net.csi["H00300"][1]
        i = next(k for k, (d, _) in enumerate(rows) if d == "2026-09-24")
        rows[i] = ("2026-09-24", 1.0)
        rep = runner.update(END, only=["T01"], raw_dir=self.raw, out_dir=self.out, log=self.log.append)
        tr = next(r for r in rep if r["file"] == "H00300.csv")
        self.assertEqual((tr["added"], tr["revised"], tr["since"]), (2, 1, "2026-09-15"))
        self.assertEqual(read_cov(self.out / "coverage.csv")["T01"]["last_date"], "2026-09-29")

    def test_update_failure_keeps_old_data(self):
        self.backfill(only=["T01"])
        before = (self.raw / "H00300.csv").read_bytes()
        del self.net.csi["H00300"]
        rep = runner.update(END, only=["T01"], raw_dir=self.raw, out_dir=self.out, log=self.log.append)
        self.assertFalse(next(r for r in rep if r["file"] == "H00300.csv")["ok"])
        self.assertEqual((self.raw / "H00300.csv").read_bytes(), before)

    def test_package_truncates_and_verifies(self):
        self.backfill(only=["T01", "T16"])
        dest = runner.package(date(2026, 9, 18), raw_dir=self.raw, out_dir=self.out, pkg_root=self.tmp, log=self.log.append)
        self.assertEqual(dest.name, "research-package-2026-09-18")
        self.assertEqual(store.read(dest / "raw" / "H00300.csv")[-1]["date"], "2026-09-18")
        cov = read_cov(dest / "coverage.csv")
        self.assertEqual((cov["T01"]["last_date"], cov["T01"]["exec_last_date"]), ("2026-09-18", "2026-09-18"))
        meta = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["raw_files"], 5)
        self.assertEqual(runner.verify(dest), [])
        with open(dest / "raw" / "H00300.csv", "a", encoding="utf-8") as f:
            f.write("2026-09-19,1,1,1,1,,,csi\n")
        (dest / "raw" / "extra.csv").write_text("x", encoding="utf-8")
        self.assertEqual(runner.verify(dest), ["哈希不符 raw/H00300.csv", "清单外文件 raw/extra.csv"])

    def test_package_refuses_to_overwrite(self):
        self.backfill(only=["T01"])
        runner.package(END, raw_dir=self.raw, out_dir=self.out, pkg_root=self.tmp, log=self.log.append)
        with self.assertRaises(SystemExit):
            runner.package(END, raw_dir=self.raw, out_dir=self.out, pkg_root=self.tmp, log=self.log.append)


class Store(unittest.TestCase):
    def test_merge_refuses_other_source(self):
        old = [{"date": "2026-09-24", "close": "1", "source": "eia"}]
        with self.assertRaises(store.MixError):
            store.merge(old, [{"date": "2026-09-25", "close": 2.0}], "yahoo")

    def test_file_names(self):
        self.assertEqual(store.file_name("^XNDX", "yahoo"), "XNDX.csv")
        self.assertEqual(store.file_name("BZ=F", "yahoo"), "BZ_F.csv")
        self.assertEqual(store.file_name("518880", "eastmoney_etf_hfq"), "518880.hfq.csv")


class Compare(unittest.TestCase):
    def test_subtractive_qfq_steps(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        raw = [("2026-06-01", 3.0), ("2026-06-02", 3.1), ("2026-06-03", 3.0), ("2026-06-04", 3.05)]
        div = {"2026-06-01": 0.1, "2026-06-02": 0.1}           # 06-03 除息 0.1：此前 qfq = raw − 0.1
        store.write(tmp / "raw.csv", [{"date": d, "close": c, "source": "eastmoney_etf"} for d, c in raw])
        store.write(tmp / "ref.csv", [{"date": d, "close": round(c - div.get(d, 0), 4)} for d, c in raw])
        res = runner.compare(tmp / "ref.csv", tmp / "raw.csv", out=tmp / "diff.csv")
        self.assertEqual((res["overlap"], res["equal"]), (4, 2))
        self.assertEqual([s["date"] for s in res["steps"]], ["2026-06-03"])
        self.assertTrue((tmp / "diff.csv").exists())


if __name__ == "__main__":
    unittest.main()
