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
from src.indicators.calendar import load_trading_days, next_trading_day   # noqa: E402
from src.indicators.metrics import atr20, month_end_flags, rs_1m, z_month   # noqa: E402
from src.indicators.states import form_states                   # noqa: E402
from src.research.prereg_v1 import run as prereg_run             # noqa: E402
from src.research.prereg_v1.panel import ew_daily_returns, reference_atr   # noqa: E402


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
        full = B.container_panel(df, bench, end_full, compute_indicators=True)
        for cut in (300, 517, 640, 899):
            cd = df["date"].iloc[cut].date()
            part = B.container_panel(df.iloc[: cut + 1].reset_index(drop=True), bench[bench.index <= df["date"].iloc[cut]], cd,
                                     compute_indicators=True)
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
        self.assertEqual(month_end_flags(dates, date(2026, 9, 30)).tolist(), [False, True, False, False])   # 停更的序列不在月中冒出 z
        done = pd.Series(pd.to_datetime(["2026-09-29", "2026-09-30"]))
        self.assertEqual(month_end_flags(done, date(2026, 9, 30)).tolist(), [False, True])

    def test_weekend_month_end_is_recognised_on_the_day(self):
        # 2026-10-30 是周五、10-31 是周六：当天就要认作月末，否则每日任务会漏掉这次恐慌信号
        dates = pd.Series(pd.to_datetime(["2026-10-29", "2026-10-30"]))
        self.assertEqual(month_end_flags(dates, date(2026, 10, 30)).tolist(), [False, True])

    def test_calendar_recognises_holiday_month_end_on_the_day(self):
        """v1.1-e：月底最后一个工作日是节假日时，有交易日历就能当天认出月末；日历没覆盖到则退回工作日规则。"""
        dates = pd.Series(pd.to_datetime(["2026-06-26", "2026-06-29"]))
        cal = pd.bdate_range("2026-06-01", "2026-07-31").difference(pd.to_datetime(["2026-06-30"]))   # 假设 06-30 休市
        self.assertEqual(month_end_flags(dates, date(2026, 6, 29)).tolist(), [False, False])           # 无日历：要等下一行
        self.assertEqual(month_end_flags(dates, date(2026, 6, 29), cal).tolist(), [False, True])
        short = pd.bdate_range("2026-06-01", "2026-06-29")                                              # 日历只到 06-29
        self.assertEqual(month_end_flags(dates, date(2026, 6, 29), short).tolist(), [False, False])
        stale = pd.Series(pd.to_datetime(["2026-06-10", "2026-06-11"]))                                 # 停更序列仍不在月中冒出 z
        self.assertEqual(month_end_flags(stale, date(2026, 6, 29), cal).tolist(), [False, False])
        long = pd.Series(pd.bdate_range("2024-06-01", "2026-06-29").difference(pd.to_datetime(["2026-06-30"])))
        close = pd.Series(np.linspace(100, 80, len(long)))
        self.assertTrue(np.isnan(z_month(close, long, date(2026, 6, 29)).iloc[-1]))
        self.assertTrue(np.isfinite(z_month(close, long, date(2026, 6, 29), trading_days=cal).iloc[-1]))

    def test_calendar_file(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "a.csv").write_text("﻿trade_date\n2026-09-29\n20260930\n2026-10-08\n\n2026-09-29\n", encoding="utf-8")
        days = load_trading_days(tmp / "a.csv")
        self.assertEqual([d.date().isoformat() for d in days], ["2026-09-29", "2026-09-30", "2026-10-08"])
        self.assertEqual(next_trading_day(date(2026, 9, 30), days), date(2026, 10, 8))
        self.assertIsNone(next_trading_day(date(2026, 10, 8), days))
        self.assertIsNone(load_trading_days(tmp / "missing.csv"))                               # 没有文件：退回工作日规则
        bad = {"empty": "date\n",
               "two_columns": "date,jybz\n2026-10-30,1\n2026-10-31,0\n",                        # 原样导出的开市标志
               "weekend": "2026-10-30\n2026-10-31\n",
               "gap": "2026-10-14\n2026-10-15\n2026-12-01\n",                                   # 中间缺一段：月中会误判月末
               "junk": "date\n2026-10-14\nxx\n"}
        for k, text in bad.items():
            (tmp / f"{k}.csv").write_text(text, encoding="utf-8")
            with self.subTest(k), self.assertRaises(ValueError):                              # 文件在但不对：报错，不静默退回
                load_trading_days(tmp / f"{k}.csv")

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

    def make_package(self, with_bench=True, calendar=None):
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
                                   pkg_root=self.tmp, calendar=calendar, log=lambda *_: None)

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
        bench = pd.read_csv(out / "bench.csv", parse_dates=["date"])
        self.assertTrue(pd.to_datetime(panel["date"]).isin(bench["date"]).all())      # I-20：全部在 A 股日历上
        self.assertEqual(rep["containers"]["原油"]["calendar"], "overseas_d_minus_1")
        self.assertEqual(rep["containers"]["原油"]["volume_source"], "none")
        self.assertEqual(prereg_run.main(["check", "--panel", str(out / "panel.csv"), "--bench", str(out / "bench.csv"),
                                          "--out", str(self.tmp / "v1")]), 0)
        raw_bench = pd.read_csv(pkg / "raw" / "H00300.csv", parse_dates=["date"]).set_index("date")
        self.assertTrue(np.allclose(bench.set_index("date")["hs300_open"], raw_bench.loc[bench["date"], "open"]))   # 基准原始开盘
        self.assertIsNone(rep["calendar_file"])

    def test_calendar_file_travels_with_package(self):
        cal = self.tmp / "sse-trading-days.csv"
        cal.write_text("date\n" + "\n".join(d.date().isoformat() for d in pd.bdate_range("2005-01-01", "2027-12-31")) + "\n",
                       encoding="utf-8")
        pkg = self.make_package(calendar=cal)
        self.assertTrue((pkg / "calendar" / "sse-trading-days.csv").exists())
        self.assertIn("calendar/sse-trading-days.csv", (pkg / "MANIFEST.sha256").read_text(encoding="utf-8"))
        self.assertTrue(__import__("json").loads((pkg / "MANIFEST.json").read_text(encoding="utf-8"))["calendar_file"])
        self.assertEqual(data_runner.verify(pkg), [])
        out = B.build(pkg, self.tmp / "panel", log=lambda *_: None)
        rep = __import__("json").loads((out / "build-report.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["calendar_file"], __import__("hashlib").sha256(cal.read_bytes()).hexdigest())
        shutil.rmtree(pkg)                                                                      # 日历坏了：build 拒绝，不退回工作日规则
        cal.write_text("date\n2026-10-30\n2026-10-31\n", encoding="utf-8")
        pkg = self.make_package(calendar=cal)
        with self.assertRaisesRegex(B.BuildError, "交易日历"):
            B.build(pkg, self.tmp / "panel2", log=lambda *_: None)

    def test_missing_total_return_bench_fails(self):
        pkg = self.make_package(with_bench=False)
        with self.assertRaisesRegex(B.BuildError, "H00300"):
            B.build(pkg, self.tmp / "panel", log=lambda *_: None)

    def test_non_positive_close_fails(self):
        pkg = self.make_package()
        raw = self.tmp / "raw2"
        shutil.copytree(pkg / "raw", raw)
        rows = store.read(raw / "BRENT.csv")
        rows[100]["close"] = "-1"
        store.write(raw / "BRENT.csv", rows)
        with self.assertRaisesRegex(B.BuildError, "收盘非正"):
            B.load_series(raw / "BRENT.csv")

    def test_tampered_package_fails(self):
        pkg = self.make_package()
        with open(pkg / "raw" / "BRENT.csv", "a", encoding="utf-8") as f:
            f.write("2026-10-01,1,1,1,1,,,eia\n")
        with self.assertRaisesRegex(B.BuildError, "MANIFEST"):
            B.build(pkg, self.tmp / "panel", log=lambda *_: None)


def _bars(dates, start=100.0, step=0.5, volume=1000.0):
    c = start + step * np.arange(len(dates))
    return pd.DataFrame({"date": pd.to_datetime(dates), "open": c - 0.1, "high": c + 0.3, "low": c - 0.3, "close": c,
                         "volume": volume})


SPRING = pd.bdate_range("2026-02-16", "2026-02-20")                     # A 股春节休市一周
CAL = pd.bdate_range("2025-12-01", "2026-03-31").difference(SPRING)     # A 股日历
US_HOLIDAYS = pd.to_datetime(["2026-01-19", "2026-02-16"])
US_DAYS = pd.bdate_range("2025-11-24", "2026-03-31").difference(US_HOLIDAYS)


class CalendarAlignment(unittest.TestCase):
    """I-20：全部容器对齐到 A 股日历；海外取本地 ≤ D−1 的最后一根 K 线，没有新 K 线写平盘。"""

    def test_overseas_takes_previous_local_bar_and_flat_bars(self):
        raw = _bars(US_DAYS)
        out, rep = B.align_to_calendar(raw, CAL, overseas=True)
        self.assertEqual(list(out["date"]), list(CAL))
        by = raw.set_index("date")
        for d, c in zip(out["date"], out["close"]):                     # 每一行都只用 D 之前的 K 线
            self.assertEqual(c, by[by.index < d]["close"].iloc[-1])
        flat = out[out["date"] == pd.Timestamp("2026-01-20")].iloc[0]  # 美股 01-19 休市：01-20 没有新 K 线
        self.assertEqual((flat.open, flat.high, flat.low, flat.close, flat.volume), (flat.close,) * 4 + (0.0,))
        self.assertGreaterEqual(rep["stale_days"], 1)
        after = out[out["date"] == pd.Timestamp("2026-02-23")].iloc[0]  # 春节后第一天：用美股 02-20 的收盘
        self.assertEqual(after.close, by.loc[pd.Timestamp("2026-02-20"), "close"])
        self.assertGreaterEqual(rep["multi_bar_days"], 1)
        self.assertEqual(rep["trailing_stale_days"], 0)

    def test_a_share_rows_off_calendar_dropped(self):
        raw = _bars(pd.bdate_range("2025-12-01", "2026-03-31"))            # 含春节那一周（假数据）
        out, rep = B.align_to_calendar(raw, CAL, overseas=False)
        self.assertEqual(rep["dropped_off_calendar"], len(SPRING))
        self.assertTrue(out["date"].isin(CAL).all())
        self.assertEqual(rep["missing_on_calendar"], 0)
        _, rep = B.align_to_calendar(raw[raw["date"] != CAL[30]], CAL, overseas=False)   # A 股序列自己缺一个交易日：不补，计数
        self.assertEqual(rep["missing_on_calendar"], 1)

    def test_trailing_flats_are_reported(self):
        raw = _bars(US_DAYS[US_DAYS <= "2026-03-20"])                       # 海外序列 03-20 以后停更
        _, rep = B.align_to_calendar(raw, CAL, overseas=True)
        self.assertEqual(rep["trailing_stale_days"], len(CAL[CAL > "2026-03-23"]))
        self.assertEqual(rep["last_bar_date"], "2026-03-20")

    def test_equal_weight_no_longer_drops_holiday_returns(self):
        a = _bars(CAL, step=0.4)
        us = _bars(US_DAYS, start=200.0, step=1.0)
        bench = a.set_index("date")["close"]
        end = CAL[-1].date()

        def panel(frames):
            out = []
            for name, df in frames.items():
                q = B.container_panel(df.reset_index(drop=True), bench, end, compute_indicators=True)
                q.insert(1, "container", name)
                out.append(q)
            return pd.concat(out, ignore_index=True)

        old = panel({"A": a, "US": us})                                     # 旧做法：各用各的日历
        aligned = panel({"A": B.align_to_calendar(a, CAL, False)[0], "US": B.align_to_calendar(us, CAL, True)[0]})
        wide = aligned.pivot(index="date", columns="container", values="close")
        self.assertEqual(int(wide.pct_change(fill_method=None).iloc[1:].isna().sum().sum()), 0)   # 没有空洞
        # 春节后第一天 02-23：A 股收益 = 02-23 / 02-13；美股收益 = 02-20 / 02-12（两个 A 股交易日各自的 D−1），跨假期收益都在
        ret = wide.pct_change(fill_method=None).loc[pd.Timestamp("2026-02-23")]
        A, U = a.set_index("date")["close"], us.set_index("date")["close"]
        self.assertAlmostEqual(ret["A"], A[pd.Timestamp("2026-02-23")] / A[pd.Timestamp("2026-02-13")] - 1)
        self.assertAlmostEqual(ret["US"], U[pd.Timestamp("2026-02-20")] / U[pd.Timestamp("2026-02-12")] - 1)
        old_wide = old.pivot(index="date", columns="container", values="close")
        old_wide = old_wide[old_wide.index >= CAL[1]]
        holes = old_wide.pct_change(fill_method=None).iloc[1:].isna().sum()
        self.assertGreater(int(holes["A"]), 0)                              # 旧做法：A 股假期后第一天的收益被丢掉
        self.assertGreater(int(holes["US"]), 0)                             #          美股假日后第一天的收益被丢掉
        r = ew_daily_returns(aligned)                                       # 对齐后：等权日收益 = 当日两个容器收益的均值，无一缺席
        both = wide.pct_change(fill_method=None).iloc[1:]
        np.testing.assert_allclose(r.loc[both.index].to_numpy(), both.mean(axis=1).to_numpy())

    def test_truncation_with_alignment(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        raw = _bars(US_DAYS)
        bench = _bars(CAL).set_index("date")["close"]
        cov = {"series_file": "NDX.csv", "route_used": "yahoo", "code": "NDX", "series_code": "NDX"}
        store.write(tmp / "NDX.csv", [{**r, "date": r["date"].date().isoformat(), "source": "yahoo"} for r in raw.to_dict("records")])
        full_df, _ = B.research_frame(tmp, cov, CAL)
        full = B.container_panel(full_df, bench, CAL[-1].date())
        for cut in (CAL[20], CAL[45], CAL[-5]):
            store.write(tmp / "cut.csv", [{**r, "date": r["date"].date().isoformat(), "source": "yahoo"}
                                          for r in raw[raw["date"] <= cut].to_dict("records")])
            part_df, _ = B.research_frame(tmp, {**cov, "series_file": "cut.csv"}, CAL[CAL <= cut])
            part = B.container_panel(part_df, bench[bench.index <= cut], cut.date())
            a = full[full["date"] <= cut].reset_index(drop=True)
            if not month_end_flags(part["date"], cut.date()).iloc[-1] and month_end_flags(full["date"], CAL[-1].date())[full["date"] == cut].any():
                a.loc[len(a) - 1, "z_month"] = np.nan
            pd.testing.assert_frame_equal(a, part.reset_index(drop=True), check_dtype=False, obj=f"cut={cut.date()}")


def _write(path: Path, df: pd.DataFrame, route: str) -> None:
    store.write(path, [{**r, "date": r["date"].date().isoformat(), "source": route} for r in df.to_dict("records")])


US_LONG = pd.bdate_range("2025-09-01", "2026-03-31").difference(US_HOLIDAYS)    # 够 50 根热身


class NativeIndicators(unittest.TestCase):
    """I-24：K 线级指标（state、ATR20）在容器原生序列上算，算完再对齐；平盘日沿用上一根；长假 K 线不合并。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bench = _bars(CAL).set_index("date")["close"]

    def frame(self, raw: pd.DataFrame, route="yahoo", cal=CAL):
        _write(self.tmp / "S.csv", raw, route)
        df, rep = B.research_frame(self.tmp, {"series_file": "S.csv", "route_used": route, "code": "S", "series_code": "S"}, cal)
        return df, rep

    def us_random(self, seed=5):
        r = ohlcv(n=len(US_LONG), seed=seed)
        return r.assign(date=US_LONG)

    def test_a_flat_day_carries_previous_indicators(self):
        df, rep = self.frame(self.us_random())
        by = df.set_index("date")
        flat, prev = pd.Timestamp("2026-01-20"), pd.Timestamp("2026-01-19")    # 美股 01-19 休市：A 股 01-20 没有新 K 线
        self.assertEqual((by.loc[flat, "open"], by.loc[flat, "volume"]), (by.loc[prev, "close"], 0.0))
        self.assertEqual(by.loc[flat, "state"], by.loc[prev, "state"])
        self.assertEqual(by.loc[flat, "atr20"], by.loc[prev, "atr20"])
        self.assertGreater(rep["stale_days"], 0)

    def test_b_each_row_equals_its_native_bar(self):
        raw = self.us_random()
        native = B.bar_indicators(B.load_series(self._raw_path(raw))[0]).set_index("date")
        df, _ = self.frame(raw)
        for d, st, a in zip(df["date"], df["state"], df["atr20"]):                  # 每一行 = 本地日期 < D 的最后一根原生 K 线的指标
            src = native[native.index < d].iloc[-1]
            self.assertEqual(st, src["state"], d)
            self.assertTrue((np.isnan(a) and np.isnan(src["atr20"])) or a == src["atr20"], d)
        after = df.set_index("date").loc[pd.Timestamp("2026-01-21")]                # 美股假日后第一根（01-20）
        self.assertEqual(after["atr20"], native.loc[pd.Timestamp("2026-01-20"), "atr20"])
        old = B.bar_indicators(df[B.BAR_COLUMNS]).set_index("date")                 # P6a 的做法：在对齐后的序列上算（平盘进窗口）
        self.assertNotEqual(old.loc[pd.Timestamp("2026-01-21"), "atr20"], after["atr20"])

    def _raw_path(self, raw):
        _write(self.tmp / "N.csv", raw, "yahoo")
        return self.tmp / "N.csv"

    def test_c_holiday_high_enters_hi20(self):
        """A 股春节（02-16~02-20）期间美股 02-18 出现一个只在假期中段的高点。对齐后 02-23 用 02-20 的 K 线，
        它的 hi20 / 区间含 02-18 的高点，BNB（收盘突破前 20 根高点且区间收窄）因此不成立。"""
        c = 100 + 0.01 * np.arange(len(US_LONG))                                  # 缓慢上行、窄幅：每根都是 BNB
        raw = pd.DataFrame({"date": US_LONG, "open": c - 0.005, "high": c + 0.005, "low": c - 0.1, "close": c, "volume": 1000.0})
        spike = raw.copy()
        spike.loc[spike["date"] == pd.Timestamp("2026-02-18"), "high"] += 5.0
        plain, _ = self.frame(raw)
        hit, _ = self.frame(spike)
        d = pd.Timestamp("2026-02-23")
        self.assertEqual(plain.set_index("date").loc[d, "state"], "BNB")
        self.assertNotEqual(hit.set_index("date").loc[d, "state"], "BNB")                                  # 假期高点进了 hi20
        self.assertGreater(hit.set_index("date").loc[d, "atr20"], plain.set_index("date").loc[d, "atr20"])   # 也进了 ATR
        native = B.bar_indicators(spike).set_index("date")
        self.assertEqual(hit.set_index("date").loc[d, "state"], native.loc[pd.Timestamp("2026-02-20"), "state"])
        # 对照：在对齐后的 K 线上算（P6a），02-18 那根根本不在序列里，有没有这个高点结果一样
        old = lambda f: B.bar_indicators(f[B.BAR_COLUMNS]).set_index("date").loc[d, ["state", "atr20"]].tolist()   # noqa: E731
        self.assertEqual(old(hit), old(plain))
        self.assertEqual(hit.set_index("date").loc[d, "high"], spike.set_index("date").loc[pd.Timestamp("2026-02-20"), "high"])  # 面板 high 是最后一根的

    def test_d_truncation_with_native_indicators(self):
        """A 股日 D 只能用本地日期 < D 的 K 线：原始数据截到 D 之前（不含 D），或把 D 及以后的价格 ×3、量 ×50，D 及以前的行都不变。"""
        raw = self.us_random(seed=9)
        full, _ = self.frame(raw)
        full_p = B.container_panel(full, self.bench, CAL[-1].date())
        cols = ["date", "open", "high", "low", "close", "state", "rs_1m", "atr20"]                # z_month 的月末判定另有截断测试
        for cut in (CAL[15], CAL[40], CAL[-3]):
            a = full_p[full_p["date"] <= cut].reset_index(drop=True)
            part, _ = self.frame(raw[raw["date"] < cut], cal=CAL[CAL <= cut])
            part_p = B.container_panel(part, self.bench[self.bench.index <= cut], cut.date())
            pd.testing.assert_frame_equal(a[cols], part_p.reset_index(drop=True)[cols], check_dtype=False, obj=f"cut={cut.date()}")
            later = raw["date"] >= cut
            noisy = raw.assign(**{c: raw[c].where(~later, raw[c] * 3) for c in ("open", "high", "low", "close")},
                               volume=raw["volume"].where(~later, raw["volume"] * 50))
            moved, _ = self.frame(noisy)
            moved_p = B.container_panel(moved, self.bench, CAL[-1].date())
            pd.testing.assert_frame_equal(a[cols], moved_p[moved_p["date"] <= cut].reset_index(drop=True)[cols], check_dtype=False,
                                          obj=f"noisy future, cut={cut.date()}")

    def test_f_panel_uses_native_indicators(self):
        """面板（V1 的输入）里海外容器的 state / atr20 逐行等于原生 K 线的值；缺指标列时报错，不静默退回 P6a 口径。"""
        raw = self.us_random(seed=3)
        df, rep = self.frame(raw)
        self.assertGreater(rep["stale_days"], 0)
        self.assertEqual(list(df.columns), B.BAR_COLUMNS + B.INDICATOR_COLUMNS)                    # amount / source 不带
        p = B.container_panel(df, self.bench, CAL[-1].date())
        native = B.bar_indicators(B.load_series(self._raw_path(raw))[0]).set_index("date")
        for d, st, a in zip(p["date"], p["state"], p["atr20"]):
            src = native[native.index < d].iloc[-1]
            self.assertEqual(st, src["state"], d)
            self.assertTrue((np.isnan(a) and np.isnan(src["atr20"])) or a == src["atr20"], d)
        old = B.container_panel(df[B.BAR_COLUMNS], self.bench, CAL[-1].date(), compute_indicators=True)   # P6a 口径
        self.assertFalse(np.allclose(old["atr20"].to_numpy(), p["atr20"].to_numpy(), equal_nan=True))
        with self.assertRaisesRegex(B.BuildError, "state / atr20"):
            B.container_panel(df[B.BAR_COLUMNS], self.bench, CAL[-1].date())

    def test_e_a_share_unchanged_from_p6a(self):
        days = pd.bdate_range("2025-06-02", "2026-03-31")
        raw = ohlcv(n=len(days), seed=11).assign(date=days)                          # 含春节一周的假行（非交易日）
        raw = raw[raw["date"] != CAL[30]]                                            # 另缺一个交易日
        cal = pd.bdate_range("2025-06-02", "2026-03-31").difference(SPRING)
        new, rep = self.frame(raw, route="csi", cal=cal)
        new_p = B.container_panel(new, self.bench, cal[-1].date())
        aligned, _ = B.align_to_calendar(B.load_series(self._raw_path(raw))[0], cal, False)   # P6a：先对齐，再在对齐后的序列上算
        old_p = B.container_panel(aligned, self.bench, cal[-1].date(), compute_indicators=True)
        pd.testing.assert_frame_equal(new_p, old_p)
        self.assertEqual((rep["dropped_off_calendar"], rep["missing_on_calendar"]), (len(SPRING), 1))


class VolumeSource(unittest.TestCase):
    """I-21：全收益指数缺成交量时借同一指数价格版本的成交量。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        days = pd.bdate_range("2026-01-05", periods=60)
        tr = _bars(days, volume=np.nan)
        px = _bars(days, volume=np.arange(60) * 10.0 + 5)
        for name, df, route in (("H00300.csv", tr, "csi"), ("000300.csv", px, "csi")):
            store.write(self.tmp / name, [{**r, "date": r["date"].date().isoformat(), "source": route} for r in df.to_dict("records")])
        self.px = px

    def test_borrowed_from_price_version(self):
        df, rep = B.research_frame(self.tmp, {"series_file": "H00300.csv", "route_used": "csi", "code": "000300",
                                              "series_code": "H00300"}, pd.DatetimeIndex(self.px["date"]))
        self.assertEqual(rep["volume_source"], "price_version")
        np.testing.assert_allclose(df["volume"].to_numpy(), self.px["volume"].to_numpy())

    def test_self_and_none(self):
        cal = pd.DatetimeIndex(self.px["date"])
        _, rep = B.research_frame(self.tmp, {"series_file": "000300.csv", "route_used": "csi", "code": "000300", "series_code": "000300"}, cal)
        self.assertEqual(rep["volume_source"], "self")
        _, rep = B.research_frame(self.tmp, {"series_file": "H00300.csv", "route_used": "csi", "code": "999999", "series_code": "H00300"}, cal)
        self.assertEqual(rep["volume_source"], "none")                      # 价格版本文件不存在


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
