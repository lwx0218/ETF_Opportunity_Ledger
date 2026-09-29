"""数据源解析与分段。只用 fixtures 与假网络，不出网。

运行：python -m unittest discover -s tests -t .
"""
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import http, sources as S          # noqa: E402
from src.data import universe as U               # noqa: E402
from tests.data.fakenet import FakeNet           # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures"


def serve(name):
    body = (FX / name).read_bytes()
    return mock.patch.object(http, "get", side_effect=lambda url, params=None, **kw: body)


class NoSleep(unittest.TestCase):
    def setUp(self):
        p = mock.patch("src.data.sources.time.sleep")
        p.start()
        self.addCleanup(p.stop)


class FixtureParse(NoSleep):
    D0, D1 = date(2026, 9, 24), date(2026, 9, 25)

    def test_csindex(self):
        with serve("csindex_000300.json"):
            got = S.fetch_csindex("000300", self.D0, self.D1)
        self.assertEqual([r["date"] for r in got.rows], ["2026-09-24", "2026-09-25"])      # 源里倒序，输出升序
        self.assertEqual(got.rows[1]["close"], 4580.4)
        self.assertEqual(got.name, "沪深300指数 / CSI 300 Index")

    def test_csindex_business_errors(self):
        bad = b'{"code":"403","msg":"blocked","data":null}'
        with mock.patch.object(http, "get", return_value=bad):                             # 全部业务错误：报出错误，不是「0 行」
            with self.assertRaisesRegex(http.FetchError, "code=403 msg=blocked"):
                S.fetch_csindex("000300", self.D0, self.D1)
        ok = (FX / "csindex_000300.json").read_bytes()
        with mock.patch.object(http, "get", side_effect=[bad, ok]):                         # 起点前出错：数据照收，但写明可能被截
            got = S.fetch_csindex("000300", date(2025, 6, 1), date(2026, 9, 25))
        self.assertEqual(len(got.rows), 2)
        self.assertIn("first_date 可能被截短", got.warnings[0])
        bad = b'{"code":"500","msg":"bad","data":null}'
        with mock.patch.object(http, "get", side_effect=[ok, bad]):
            with self.assertRaisesRegex(http.FetchError, "code=500"):
                S.fetch_csindex("000300", date(2025, 6, 1), date(2026, 9, 25))

    def test_yahoo_uses_exchange_timezone_per_bar(self):
        # 纽约 0 点的期货日线：夏令时 −4h、冬令时 −5h；只用当前 gmtoffset 会把一边整体挪一天
        from datetime import datetime, timezone
        ts = [int(datetime(2026, 10, 30, 4, tzinfo=timezone.utc).timestamp()), int(datetime(2026, 11, 3, 5, tzinfo=timezone.utc).timestamp())]
        body = json.dumps({"chart": {"error": None, "result": [{"meta": {"gmtoffset": -18000, "exchangeTimezoneName": "America/New_York"},
                           "timestamp": ts, "indicators": {"quote": [{"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [70.0, 71.0], "volume": [0, 0]}]}}]}}).encode()
        with mock.patch.object(http, "get", return_value=body):
            got = S.fetch_yahoo("BZ=F", date(2026, 10, 1), date(2026, 11, 30))
        self.assertEqual([r["date"] for r in got.rows], ["2026-10-30", "2026-11-03"])

    def test_eastmoney(self):
        with serve("eastmoney_510300.json"):
            got = S.fetch_eastmoney("1.510300", self.D0, self.D1)
        r = got.rows[0]
        # 东财字段顺序：日期,开,收,高,低,量,额
        self.assertEqual((r["open"], r["high"], r["low"], r["close"], r["volume"], r["amount"]),
                         (4.5, 4.56, 4.49, 4.55, 1000000.0, 455000000.0))
        self.assertEqual(got.name, "沪深300ETF")

    def test_tencent_column_order(self):
        with serve("tencent_sh510300.json"):
            got = S.fetch_tencent("sh510300", self.D0, self.D1)
        r = got.rows[1]
        # 腾讯行：[日期, 开, 收, 高, 低, 量]，末尾可能挂除权信息
        self.assertEqual((r["open"], r["close"], r["high"], r["low"]), (4.55, 4.53, 4.57, 4.52))
        self.assertEqual(got.name, "沪深300ETF")

    def test_tencent_never_requests_qfq(self):
        seen = []
        body = (FX / "tencent_sh510300.json").read_bytes()
        with mock.patch.object(http, "get", side_effect=lambda url, params=None, **kw: seen.append(params) or body):
            S.fetch_tencent("sh510300", self.D0, self.D1)
        self.assertTrue(all(p["param"].endswith(",400,") for p in seen))

    def test_yahoo_local_date_and_null_rows(self):
        with serve("yahoo_NDX.json"):
            got = S.fetch_yahoo("^NDX", self.D0, self.D1)
        self.assertEqual([r["date"] for r in got.rows], ["2026-09-24", "2026-09-25"])      # 收盘为 null 的一行丢弃
        self.assertEqual(got.rows[0]["close"], 21100.25)
        self.assertEqual(got.name, "NASDAQ 100")

    def test_stooq(self):
        with serve("stooq_ndx.csv"):
            got = S.fetch_stooq("^ndx", self.D0, self.D1)
        self.assertEqual(len(got.rows), 2)
        with mock.patch.object(http, "get", return_value=b"Exceeded the daily hits limit"):
            with self.assertRaises(http.FetchError):
                S.fetch_stooq("^ndx", self.D0, self.D1)

    def test_eia_needs_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(http.FetchError, "EIA_API_KEY"):
                S.fetch_eia("PET.RBRTE.D", self.D0, self.D1)

    def test_eia(self):
        with mock.patch.dict(os.environ, {"EIA_API_KEY": "k"}), serve("eia_rbrte.json"):
            got = S.fetch_eia("PET.RBRTE.D", date(2026, 9, 21), date(2026, 9, 22))
        self.assertEqual([r["close"] for r in got.rows], [67.12, 66.8])
        self.assertIsNone(got.rows[0]["open"])


class Segmentation(NoSleep):
    def setUp(self):
        super().setUp()
        self.net = FakeNet()
        p = mock.patch.object(http, "get", side_effect=self.net.get)
        p.start()
        self.addCleanup(p.stop)

    def test_csindex_by_year(self):
        self.net.add("csi", "000300", "沪深300指数", "2004-12-31", "2026-09-25")
        got = S.fetch_csindex("000300", date(2000, 1, 1), date(2026, 9, 30))
        self.assertEqual(self.net.calls.count("csi:000300"), 27)                          # 2000…2026 每年一段
        self.assertEqual((got.rows[0]["date"], got.rows[-1]["date"]), ("2004-12-31", "2026-09-25"))
        self.assertEqual(len(got.rows), len({r["date"] for r in got.rows}))

    def test_eastmoney_120_day_chunks_and_prelisting_empty(self):
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-25")
        got = S.fetch_eastmoney("1.510300", date(2010, 1, 1), date(2026, 9, 30))
        days = (date(2026, 9, 30) - date(2010, 1, 1)).days + 1
        self.assertEqual(self.net.calls.count("em:1.510300:0"), -(-days // S.EM_CHUNK_DAYS))
        self.assertEqual(got.rows[0]["date"], "2012-05-28")                              # 上市前的空段不算失败

    def test_mid_series_failure_fails_whole_series(self):
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-25")
        self.net.fail_after["em:1.510300:0"] = 10
        with self.assertRaises(http.FetchError):
            S.fetch_eastmoney("1.510300", date(2010, 1, 1), date(2026, 9, 30))

    def test_empty_segment_in_the_middle_fails(self):
        self.net.add("csi", "000905", "中证500指数", "2004-12-31", "2026-09-25")
        self.net.csi["000905"] = ("中证500指数", [(d, c) for d, c in self.net.csi["000905"][1] if not d.startswith("2011")])
        with self.assertRaisesRegex(http.FetchError, "空段"):
            S.fetch_csindex("000905", date(2000, 1, 1), date(2026, 9, 30))

    def test_eastmoney_nonzero_rc_fails(self):
        self.net.add("em", "1.518880:2", "黄金ETF", "2013-07-29", "2026-09-25")
        real = self.net.get

        def flaky(url, params=None, **kw):
            if params and str(params.get("beg", "")).startswith("2018"):
                return b'{"rc":100,"data":null}'
            return real(url, params, **kw)
        with mock.patch.object(http, "get", side_effect=flaky):
            with self.assertRaisesRegex(http.FetchError, "rc=100"):
                S.fetch_eastmoney("1.518880", date(2013, 1, 1), date(2026, 9, 30), fqt=2)

    def test_trailing_empty_last_segment_is_fine(self):
        self.net.add("em", "1.510300:0", "沪深300ETF", "2012-05-28", "2026-09-25")
        got = S.fetch_eastmoney("1.510300", date(2026, 5, 1), date(2026, 12, 31))       # 最后一段在数据之后
        self.assertEqual(got.rows[-1]["date"], "2026-09-25")

    def test_tencent_chunks_stay_under_400_rows(self):
        self.net.add("tencent", "sz399006", "创业板指", "2010-06-01", "2026-09-25")
        got = S.fetch_tencent("sz399006", date(2010, 1, 1), date(2026, 9, 30))
        self.assertEqual(got.rows[0]["date"], "2010-06-01")
        per_chunk = S.TENCENT_CHUNK_DAYS * 5 / 7 + 5
        self.assertLess(per_chunk, 400)

    def test_eia_pagination(self):
        self.net.add("eia", "PET.RBRTE.D", "Brent", "1987-05-20", "2026-09-25")
        with mock.patch.dict(os.environ, {"EIA_API_KEY": "k"}):
            got = S.fetch_eia("PET.RBRTE.D", date(1987, 1, 1), date(2026, 9, 30))
        self.assertGreater(len(got.rows), S.EIA_PAGE)
        self.assertGreater(self.net.calls.count("eia:PET.RBRTE.D"), 1)


class Redaction(NoSleep):
    def test_api_key_never_leaves_the_process(self):
        http.LOG.clear()
        with mock.patch.dict(os.environ, {"EIA_API_KEY": "SECRET123"}), \
                mock.patch("src.data.http.urlopen", side_effect=OSError("boom")), mock.patch("src.data.http.time.sleep"):
            with self.assertRaises(http.FetchError) as cm:
                S.fetch_eia("PET.RBRTE.D", date(2026, 9, 1), date(2026, 9, 2))
        self.assertNotIn("SECRET123", str(cm.exception))
        self.assertIn("api_key=***", str(cm.exception))
        self.assertTrue(http.LOG and all("SECRET123" not in json.dumps(e) for e in http.LOG))


class Mapping(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(U.index_secid("399006"), "0.399006")
        self.assertEqual(U.index_secid("000300"), "1.000300")
        self.assertIsNone(U.index_secid("H30184"))          # 中证 H / 93 代码不猜东财编码
        self.assertEqual(U.fund_secid("518880"), "1.518880")
        self.assertEqual(U.fund_secid("159915"), "0.159915")
        self.assertEqual(U.fund_secid("160723"), "0.160723")
        self.assertEqual(U.fund_tencent("159915"), "sz159915")
        self.assertEqual(U.index_tencent("000300"), "sh000300")
        self.assertEqual(U.yahoo_symbol("^XNDX"), "^XNDX")
        self.assertEqual(U.yahoo_symbol("SPX"), "^GSPC")

    def test_tr_candidates(self):
        uni = {r["theme_id"]: r for r in U.load()}
        self.assertEqual(U.tr_candidates(uni["T04"]), ["H00688", "000688CNY010"])
        self.assertEqual(U.tr_candidates(uni["T33"]), ["H11077", "H11077CNY010"])    # 自由文本里只取像代码的片段
        self.assertEqual(U.tr_candidates(uni["T35"]), ["^XNDX"])
        self.assertEqual(U.tr_candidates(uni["T15"]), [])

    def test_universe_counts(self):
        uni = U.load()
        self.assertEqual(len(uni), 39)
        self.assertEqual(sum(1 for r in uni if U.in_panel(r)), 37)
        self.assertTrue(all(r["research_route"] in U.RESEARCH_CHAIN for r in uni if U.in_panel(r)))


if __name__ == "__main__":
    unittest.main()
