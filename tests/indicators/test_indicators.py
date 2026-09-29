"""指标层：与 kell_states 逐日一致、无未来函数、z_month 口径、数据包 → 长表 → run check 端到端。只用构造数据。

运行：python -m unittest discover -s tests -t .
"""
import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timezone
from unittest import mock
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import runner as data_runner, store               # noqa: E402
from src.indicators import build as B                           # noqa: E402
from src.indicators.metrics import atr20, month_end_flags, rs_1m, z_month   # noqa: E402
from src.indicators.states import form_states                   # noqa: E402
from src.research.prereg_v1 import run as prereg_run             # noqa: E402
from src.research.prereg_v1.panel import reference_atr           # noqa: E402


def legacy_probe():
    """src/rotation/etf_probe.py 顶层 import akshare；与 analyze.py 相同，注入伪模块后加载。"""
    sys.modules.setdefault("akshare", types.ModuleType("akshare"))
    spec = importlib.util.spec_from_file_location("etf_probe_legacy", ROOT / "src" / "rotation" / "etf_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ohlcv(n=900, seed=0, start="2012-01-02", volume=True):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    c = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, n) + 0.01 * np.sin(np.arange(n) / 25))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.01, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.01, n))
    v = rng.lognormal(10, 0.6, n) if volume else np.full(n, np.nan)
    return pd.DataFrame({"date": dates, "open": o, "high": h, "low": l, "close": c, "volume": v})


class StatePort(unittest.TestCase):
    def test_identical_to_kell_states(self):
        probe = legacy_probe()
        for seed in range(5):
            df = ohlcv(seed=seed)
            old = probe.kell_states(df)
            new = form_states(df)
            self.assertTrue(old["kell"].equals(new["state"]), seed)
            for a, b in (("ema10", "ema10"), ("ema20", "ema20"), ("atr", "atr14"), ("ext", "ext")):
                pd.testing.assert_series_equal(old[a], new[b], check_names=False)
            self.assertGreater(new["state"].nunique(), 5)            # 构造数据确实走到了多数分支

    def test_no_volume_never_hits_volume_states(self):
        st = form_states(ohlcv(volume=False))["state"]
        self.assertFalse(st.isin(["POP", "REV", "EXH", "DROP"]).any())

    def test_atr20_matches_reference(self):
        df = ohlcv()
        pd.testing.assert_series_equal(atr20(df), reference_atr(df), check_names=False)


class NoLookahead(unittest.TestCase):
    """截断测试：把 cut 之后的数据删掉，cut 及以前的每一个值都不变（做法同 tests/research/test_prereg_v1.py::test_no_lookahead）。"""

    def test_truncation_does_not_change_past(self):
        df = ohlcv(n=900)
        bench = ohlcv(n=900, seed=9).set_index("date")["close"]
        end_full = df["date"].iloc[-1].date()
        full = B.container_panel(df, bench, end_full)
        for cut in (300, 517, 640, 899):
            cd = df["date"].iloc[cut].date()
            part = B.container_panel(df.iloc[: cut + 1].reset_index(drop=True), bench[bench.index <= df["date"].iloc[cut]], cd)
            a = full.iloc[: cut + 1].reset_index(drop=True)
            # 截断点若恰是日历月末之前的最后交易日，截断版不知道这个月是否已结束：只在最后一行放宽 z_month
            if not month_end_flags(part["date"], cd).iloc[-1] and month_end_flags(full["date"], end_full).iloc[cut]:
                a.loc[cut, "z_month"] = np.nan
            pd.testing.assert_frame_equal(a, part.reset_index(drop=True), check_dtype=False, obj=f"cut={cut}")


class ZMonth(unittest.TestCase):
    def test_definition(self):
        dates = pd.Series(pd.bdate_range("2020-01-01", "2023-06-30"))
        close = pd.Series(np.arange(len(dates), dtype=float) + 100)
        z = z_month(close, dates, date(2023, 6, 30))
        flag = month_end_flags(dates, date(2023, 6, 30))
        self.assertTrue(z[~flag].isna().all())                     # 只在月末有值
        m = close[flag].reset_index(drop=True)
        self.assertEqual(int(z.notna().sum()), len(m) - 20)         # 前 20 个月末不够 20 个已完成月末
        k = 25
        prev = m.iloc[k - 20:k]
        self.assertAlmostEqual(z[flag].iloc[k], (m.iloc[k] - prev.mean()) / prev.std(ddof=1))

    def test_partial_last_month_is_not_month_end(self):
        dates = pd.Series(pd.to_datetime(["2026-08-28", "2026-08-31", "2026-09-01", "2026-09-25"]))
        self.assertEqual(month_end_flags(dates, date(2026, 9, 25)).tolist(), [False, True, False, False])
        self.assertEqual(month_end_flags(dates, date(2026, 9, 30)).tolist(), [False, True, False, True])

    def test_rs_1m_uses_past_bench_only(self):
        dates = pd.Series(pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]))
        close = pd.Series([1.0, 1.1, 1.21])
        bench = pd.Series([10.0, 20.0], index=pd.to_datetime(["2026-01-02", "2026-01-07"]))   # 01-05、01-06 无基准
        r = rs_1m(close, dates, bench, n=1)
        self.assertAlmostEqual(r.iloc[1], 0.1)                     # 基准沿用 01-02，不偷看 01-07
        self.assertAlmostEqual(r.iloc[2], 0.1)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        clock = mock.patch("src.data.runner._utcnow", return_value=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)

    def make_package(self, with_bench=True):
        raw, out = self.tmp / "raw", self.tmp / "out"
        series = {"H00300.csv": (ohlcv(seed=1, start="2005-01-04", n=5600), "csi"),
                  "H30184CNY010.csv": (ohlcv(seed=2, start="2005-01-04", n=5600), "csi"),
                  "518880.hfq.csv": (ohlcv(seed=3, start="2013-07-29", n=3400), "eastmoney_etf_hfq"),
                  "BRENT.csv": (ohlcv(seed=4, start="2005-01-04", n=5600, volume=False), "eia")}
        if not with_bench:
            series.pop("H00300.csv")
        for name, (df, route) in series.items():
            d = df.copy()
            if route == "eia":
                d[["open", "high", "low"]] = np.nan
            d["date"] = d["date"].dt.strftime("%Y-%m-%d")
            d["source"] = route
            store.write(raw / name, d.to_dict("records"))
        cov = [dict(theme_id="T01", container="沪深300", status="retained", series_file="H00300.csv", route_used="csi", price_only="False"),
               dict(theme_id="T06", container="半导体", status="retained", series_file="H30184CNY010.csv", route_used="csi", price_only="False"),
               dict(theme_id="T15", container="原油", status="flagged", series_file="BRENT.csv", route_used="eia", price_only="False"),
               dict(theme_id="T16", container="黄金", status="flagged", series_file="518880.hfq.csv", route_used="eastmoney_etf_hfq", price_only="False"),
               dict(theme_id="T36", container="纳指科技", status="flagged", error="yahoo: 404"),
               dict(theme_id="T34", container="现金", status="execution_only")]
        data_runner.write_coverage(out / "coverage.csv", cov, [c["theme_id"] for c in cov])
        return data_runner.package(date(2026, 9, 30), uni_path=ROOT / "data" / "universe.csv", raw_dir=raw, out_dir=out,
                                   pkg_root=self.tmp, log=lambda *_: None)

    def test_package_to_panel_to_check(self):
        pkg = self.make_package()
        out = B.build(pkg, self.tmp / "panel", log=lambda *_: None)
        panel = pd.read_csv(out / "panel.csv")
        self.assertEqual(list(panel.columns), B.PANEL_COLUMNS)
        self.assertEqual(set(panel["container"].unique()), {"原油", "半导体", "沪深300", "黄金"})
        rep = __import__("json").loads((out / "build-report.json").read_text(encoding="utf-8"))
        self.assertIn("纳指科技", rep["skipped"])
        self.assertGreater(rep["containers"]["原油"]["ohl_filled_from_close"], 5000)
        self.assertEqual(rep["containers"]["原油"]["volume_missing_or_zero"], rep["containers"]["原油"]["rows"])
        hs = panel[panel["container"] == "沪深300"]
        self.assertTrue(np.allclose(hs["rs_1m"].dropna(), 0))       # 基准自己对自己
        self.assertEqual(prereg_run.main(["check", "--panel", str(out / "panel.csv"), "--bench", str(out / "bench.csv"),
                                          "--out", str(self.tmp / "v1")]), 0)

    def test_missing_total_return_bench_fails(self):
        pkg = self.make_package(with_bench=False)
        with self.assertRaisesRegex(B.BuildError, "H00300"):
            B.build(pkg, self.tmp / "panel", log=lambda *_: None)

    def test_tampered_package_fails(self):
        pkg = self.make_package()
        with open(pkg / "raw" / "BRENT.csv", "a", encoding="utf-8") as f:
            f.write("2026-10-01,1,1,1,1,,,eia\n")
        with self.assertRaisesRegex(B.BuildError, "MANIFEST"):
            B.build(pkg, self.tmp / "panel", log=lambda *_: None)


class LegacyCheck(unittest.TestCase):
    def test_against_analyze_py_format(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        probe = legacy_probe()
        rows = []
        bench = ohlcv(seed=11, start="2025-03-03", n=400)
        for code, seed in (("510300", 11), ("512760", 12)):
            h = ohlcv(seed=seed, start="2025-03-03", n=400)
            h[["date", "open", "close", "high", "low", "volume"]].to_csv(tmp / f"kline_{code}.csv", index=False)
            k = probe.kell_states(h)
            b = bench.set_index("date")["close"].reindex(h["date"]).ffill().values
            k["rs_1m"] = h["close"].pct_change(21) - pd.Series(b).pct_change(21)
            k["code"] = code
            rows.append(k[k["date"] >= "2025-12-01"])
        pd.concat(rows).to_csv(tmp / "panel_daily.csv", index=False)
        res = B.legacy_check(tmp)
        self.assertEqual({k: (v["state_diff"], v["ext_diff"], v["rs_1m_diff"]) for k, v in res.items()},
                         {"510300": (0, 0, 0), "512760": (0, 0, 0)})


if __name__ == "__main__":
    unittest.main()
