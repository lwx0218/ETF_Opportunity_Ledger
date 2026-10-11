"""daily/live 全池门禁，仅构造临时库，不运行扫描或真实研究。"""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src.data import db as DB
from src.jobs.live import live_panel
from src.jobs.__main__ import main as jobs_main
from src.jobs import rules as R
from tests.marketdb import put


class LiveInputs(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.db = Path(self.scratch.name) / "market.sqlite"
        self.days = pd.bdate_range("2004-09-01", "2004-12-31")
        self.end = date(2004, 12, 15)
        self.con = DB.connect(self.db)
        self.addCleanup(self.con.close)
        DB.load_calendar(self.con, self.days)
        self.covs = [dict(theme_id="T01", container="沪深300", status="retained", code="000300",
                          series_code="H00300", series_adj="raw", route_used="csi"),
                     dict(theme_id="T02", container="测试容器", status="flagged", code="000852",
                          series_code="H00852", series_adj="raw", route_used="csi")]
        self.declare(self.covs)
        for code in ("H00300", "H00852"):
            put(self.con, code, self.bars(), "csi")

    def declare(self, covs):
        DB.load_universe(self.con, [{"theme_id": c["theme_id"], "theme": c["container"], "status": c["status"]}
                                  for c in covs], "synthetic-live-inputs")
        run = DB.start_run(self.con, "backfill")
        DB.write_coverage(self.con, run, covs)
        DB.finish_run(self.con, run)

    def bars(self):
        close = 100 + np.arange(len(self.days), dtype=float)
        return pd.DataFrame(dict(date=self.days, open=close - 0.1, high=close + 2, low=close - 2,
                                 close=close, volume=1000.0))

    def read(self, **kwargs):
        before = DB.sha256_file(self.db)
        try:
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("必须离线")):
                return live_panel(self.db, self.end, **kwargs)
        finally:
            self.assertEqual(DB.sha256_file(self.db), before)

    def test_official_calendar_and_pre2005_history_preserved(self):
        # 周末坏行情留在原库，计算只认 calendar；基准不靠 OHL 填收盘。
        row = self.bars().iloc[[0]].assign(date=pd.Timestamp("2004-09-04"), close=99999.0)
        put(self.con, "H00300", pd.concat([self.bars(), row]), "csi")
        panel, bench, _, problems = self.read()
        self.assertEqual(bench.index[0], self.days[0])
        self.assertEqual(bench.index[-1].date(), self.end)
        self.assertNotIn(pd.Timestamp("2004-09-04"), bench.index)
        self.assertEqual(set(panel["container"]), {"沪深300", "测试容器"})
        self.assertEqual(problems, [])

    def test_missing_calendar_and_supplied_fallback_rejected(self):
        with self.con:
            self.con.execute("DELETE FROM calendar")
        with self.assertRaisesRegex(SystemExit, "缺官方交易日历"):
            self.read(trading_days=self.days)

    def test_caller_calendar_cannot_override_official(self):
        with self.assertRaisesRegex(SystemExit, "官方 calendar 不一致"):
            self.read(trading_days=self.days[1:])

    def test_all_declared_containers_required(self):
        self.declare(self.covs + [dict(theme_id="T03", container="缺数据容器", status="retained",
                                       series_code="MISSING", series_adj="raw", route_used="csi")])
        with self.assertRaisesRegex(SystemExit, "缺数据容器.*无窗口内真实行情"):
            self.read()

    def test_missing_coverage_and_missing_series_rejected(self):
        for sql in ("DELETE FROM coverage WHERE theme_id='T02'", "DELETE FROM bars WHERE code='H00852'"):
            with self.subTest(sql=sql):
                self.declare(self.covs)
                put(self.con, "H00852", self.bars(), "csi")
                with self.con:
                    self.con.execute(sql)
                with self.assertRaisesRegex(SystemExit, "测试容器"):
                    self.read()

    def test_missing_close_or_ohl_and_source_mismatch_rejected(self):
        for change, expected in (({"open": np.nan}, "缺真实 OHLC"),
                                 ({"close": np.nan}, "缺交易日收盘")):
            with self.subTest(change=change):
                bad = self.bars()
                for field, value in change.items():
                    bad.loc[40, field] = value
                put(self.con, "H00852", bad, "csi")
                with self.assertRaisesRegex(SystemExit, expected):
                    self.read()
        with self.con:
            self.con.execute("DELETE FROM bars WHERE code='H00852'")
        put(self.con, "H00852", self.bars(), "eia")
        with self.assertRaisesRegex(SystemExit, "来源与 coverage 不符"):
            self.read()

    def test_missing_benchmark_day_not_silently_calendar(self):
        with self.con:
            self.con.execute("DELETE FROM bars WHERE code='H00300' AND date=?", (self.days[20].date().isoformat(),))
        with self.assertRaisesRegex(SystemExit, "H00300：缺交易日收盘"):
            self.read()

    def test_close_only_benchmark_is_not_strategy_ohlc(self):
        # 基准独立资格不要求 OHL；只保留另一策略容器，不能在读取时替基准造开盘。
        with self.con:
            self.con.execute("DELETE FROM coverage WHERE theme_id='T01'")
        self.declare(self.covs[1:])
        put(self.con, "H00300", self.bars().assign(open=np.nan, high=np.nan, low=np.nan), "csi")
        panel, bench, opening, _ = self.read()
        self.assertEqual(set(panel["container"]), {"测试容器"})
        self.assertTrue(bench.notna().all())
        self.assertTrue(opening.isna().all())

    def test_future_volume_cannot_change_historical_live(self):
        past = self.bars()[self.bars()["date"] <= pd.Timestamp(self.end)].assign(volume=np.nan)
        put(self.con, "H00852", past, "csi")
        put(self.con, "000852", self.bars(), "csi")
        before = self.read()[0]
        future = self.bars()[self.bars()["date"] > pd.Timestamp(self.end)]
        # 足够长的未来有量行会把全库的缺量比率降到一半以下，不能影响截至 D 的 I-21 选择。
        later = pd.bdate_range("2005-01-03", periods=150)
        extension = pd.DataFrame(dict(date=later, open=99.0, high=102.0, low=98.0, close=100.0, volume=9000.0))
        put(self.con, "H00852", pd.concat([past, future, extension]), "csi")
        after = self.read()[0]
        pd.testing.assert_frame_equal(before, after)

    def test_old_envelope_repair_retained_for_research(self):
        bad = self.bars()
        bad.loc[40, "high"] = bad.loc[40, "close"] - 1
        put(self.con, "H00852", bad, "csi")
        panel = self.read()[0]
        repaired = panel[(panel["container"] == "测试容器") & (panel["date"] == self.days[40])].iloc[0]
        self.assertEqual(repaired["high"], repaired["close"])

    def test_overseas_end_day_only_is_not_consumable(self):
        self.declare([self.covs[0], {**self.covs[1], "route_used": "yahoo"}])
        put(self.con, "H00852", self.bars()[self.bars()["date"] == pd.Timestamp(self.end)], "yahoo")
        with self.assertRaisesRegex(SystemExit, "D−1 边界内无可用原生行情"):
            self.read()

    def test_overseas_flat_day_and_data_hole_policy_preserved(self):
        self.declare([self.covs[0], {**self.covs[1], "route_used": "yahoo"}])
        native = self.bars()[self.bars()["date"] <= "2004-12-06"]
        put(self.con, "H00852", native, "yahoo")
        panel, _, _, problems = self.read()
        foreign = panel[panel["container"] == "测试容器"].set_index("date")
        self.assertEqual(foreign.loc["2004-12-13", "data_hole"], 0)
        self.assertEqual(foreign.loc["2004-12-14", "data_hole"], 1)
        self.assertEqual(foreign.loc["2004-12-15", "open"], native.iloc[-1]["close"])
        self.assertTrue(any("2004-12-06" in p and "可能停更" in p for p in problems))

    def test_failure_precedes_ledger_creation_or_daily_job(self):
        bad = self.bars()
        bad.loc[40, "open"] = np.nan
        put(self.con, "H00852", bad, "csi")
        root = Path(self.scratch.name)
        config = root / "synthetic-rules.json"
        config.write_text(json.dumps({"confirmed_terms": R.TERMS_VERSION,
                                     "恐慌下轨": {"enabled": True, **R.RULE_R}}), encoding="utf-8")
        ledger = root / "ledger.sqlite"
        before = DB.sha256_file(self.db)
        with mock.patch("src.jobs.__main__.DailyJob", side_effect=AssertionError("门禁失败不得创建作业")):
            with self.assertRaisesRegex(SystemExit, "缺真实 OHLC"):
                jobs_main(["daily", "--no-update", "--date", self.end.isoformat(), "--market", str(self.db),
                           "--db", str(ledger), "--rules", str(config)])
        self.assertFalse(ledger.exists())
        self.assertEqual(DB.sha256_file(self.db), before)
