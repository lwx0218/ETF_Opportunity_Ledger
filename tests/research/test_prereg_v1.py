"""prereg-v1 框架的规则测试。只用构造数据，不接触任何真实行情。

运行：python -m unittest discover -s tests -v
"""
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import tests  # noqa: E402,F401 — 置位 ETF_LEDGER_TESTING：直接当脚本跑时也只许连临时库

from src.indicators.build import write_panel_db                             # noqa: E402
from src.research.prereg_v1 import run as runner                          # noqa: E402
from src.research.prereg_v1.characterize import characterize               # noqa: E402
from src.research.prereg_v1.config import Params                           # noqa: E402
from src.research.prereg_v1.engine import random_entry_null, simulate      # noqa: E402
from src.research.prereg_v1.metrics import acceptance, is_fragile, r_stats # noqa: E402
from src.research.prereg_v1.panel import (PanelError, ew_daily_returns,    # noqa: E402
                                          reference_atr, validate_panel)
from src.research.prereg_v1.signals import all_signals, breakout_signals, rs_top_flags   # noqa: E402

DATES = pd.bdate_range("2020-01-01", periods=400)
P1 = Params(rs_top_pct=1.0)          # 与相对强弱无关的测试：放开前 20% 门槛，只测其余规则


def make(closes: dict, states: dict = None, rs: dict = None, atr: float = 2.0, opens: dict = None, z: dict = None,
         holes: dict = None):
    """closes: 容器 → 收盘序列；opens 默认等于前一日收盘；states/rs/z: 容器 → {日序号: 值}；holes: 容器 → data_hole = 1 的日序号集合。"""
    rows = []
    for c, cl in closes.items():
        cl = np.asarray(cl, float)
        op = np.r_[cl[0], cl[:-1]] if not opens or c not in opens else np.asarray(opens[c], float)
        for i, d in enumerate(DATES[: len(cl)]):
            o, x = op[i], cl[i]
            rows.append(dict(date=d, container=c, open=o, high=max(o, x) + 0.1, low=min(o, x) - 0.1, close=x,
                             state=(states or {}).get(c, {}).get(i, "NEUTRAL"),
                             rs_1m=(rs or {}).get(c, {}).get(i, 0.0), atr20=atr,
                             z_month=(z or {}).get(c, {}).get(i, np.nan), data_hole=int(i in (holes or {}).get(c, ()))))
    return validate_panel(pd.DataFrame(rows))


def flat(n=300, v=100.0):
    return [v] * n


def run(panel, p=None, n=None):
    return simulate(panel, p or P1, DATES[0], DATES[(n or len(panel["date"].unique())) - 1])


class PanelTests(unittest.TestCase):
    def test_missing_column(self):
        df = make({"A": flat(5)}).drop(columns="atr20")
        with self.assertRaises(PanelError):
            validate_panel(df)

    def test_duplicate_rows(self):
        df = make({"A": flat(5)})
        with self.assertRaises(PanelError):
            validate_panel(pd.concat([df, df.iloc[[0]]]))

    def test_negative_price_rejected(self):
        df = make({"A": flat(5)})
        df.loc[0, ["open", "high", "low", "close"]] = [-1, -0.5, -1.5, -1]
        with self.assertRaises(PanelError):
            validate_panel(df)

    def test_reference_atr(self):
        df = pd.DataFrame({"high": [11, 12, 13.0], "low": [9, 10, 10.0], "close": [10, 11, 12.0]})
        # TR: 2, max(2, 2, 0)=2, max(3, 2, 1)=3 → 2 日均值 = 2.5
        self.assertAlmostEqual(reference_atr(df, 2).iloc[-1], 2.5)

    def test_ew_returns(self):
        pn = make({"A": [100, 110], "B": [100, 90]})
        self.assertAlmostEqual(ew_daily_returns(pn).iloc[1], 0.0)


class SignalTests(unittest.TestCase):
    def test_rs_top_20pct(self):
        names = [f"C{i}" for i in range(10)]
        pn = make({c: flat(3) for c in names}, states={c: {1: "XB"} for c in names},
                  rs={c: {1: float(i)} for i, c in enumerate(names)})
        s = breakout_signals(pn, Params())
        self.assertEqual(sorted(s["container"]), ["C8", "C9"])            # 10 个里前 20% = 2 个

    def test_state_must_be_entry(self):
        pn = make({"A": flat(3), "B": flat(3)}, states={"A": {1: "EXH"}, "B": {1: "REV"}}, rs={"A": {1: 5}, "B": {1: 4}})
        self.assertTrue(breakout_signals(pn, Params()).empty)            # I-01：REV 不在 v1 可进态

    def test_cooldown(self):
        st = {i: "BNB" for i in range(40)}
        pn = make({"A": flat(40), "B": flat(40)}, states={"A": st}, rs={"A": {i: 1 for i in range(40)}})
        s = breakout_signals(pn, P1)
        self.assertEqual(list(s["date"]), [DATES[0], DATES[21]])         # 第 1–20 天被冷却，第 21 天可再触发

    def test_stop_level(self):
        pn = make({"A": flat(3), "B": flat(3)}, states={"A": {1: "POP"}}, rs={"A": {1: 1}}, atr=2.5)
        s = all_signals(pn, P1)
        self.assertAlmostEqual(s.loc[0, "stop_level"], 100 - 2 * 2.5)

    def test_panic(self):
        pn = make({"A": flat(3), "B": flat(3)}, z={"A": {1: -2.1}, "B": {1: -1.9}})
        s = all_signals(pn, Params())
        self.assertEqual(list(zip(s["container"], s["branch"])), [("A", "恐慌")])


class DataHoleTests(unittest.TestCase):
    """I-25：data_hole = 1 的行（数据断档上的平盘占位）不产生入场信号，也不占 20 日冷却；已持仓照引擎处理。
    标记形状与 build 产出的一致：30 行平盘（100–129）里，连续平盘数到第 5 行起（104–129）才标 1。"""
    FLAT = set(range(100, 130))                                          # 30 行平盘
    HOLE = set(range(104, 130))                                          # build 只标第 5 行起

    def panel(self, holes=None, n=200):
        st = {i: "BNB" for i in range(n)}                                # 每天都是可进态：信号只由冷却与断档决定
        z = {i: -2.5 for i in (101, 110, 125, 150)}                      # 101 在平盘前 4 行；110、125 在断档里；150 在断档后
        return make({"A": flat(n), "B": flat(n)}, states={"A": st}, rs={"A": {i: 1 for i in range(n)}}, z={"A": z},
                    holes={"A": holes} if holes else None)

    def test_no_signal_inside_the_hole(self):
        s = all_signals(self.panel(self.HOLE), P1)
        idx = {d: i for i, d in enumerate(DATES)}
        inside = [idx[d] for d in s["date"] if idx[d] in self.HOLE]
        self.assertEqual(inside, [])                                      # 突破与恐慌两个分支都没有
        panic = set(s.loc[s["branch"] == "恐慌", "date"])
        self.assertIn(DATES[150], panic)
        self.assertIn(DATES[101], panic)                                  # 平盘前 4 行没标：当时与真实休市无法区分，照常出信号

    def test_signals_outside_the_hole_as_if_hole_rows_carried_nothing(self):
        """断档行等于「没有信号的行」：与把这些行的状态改成非可进态、z 清空的面板，信号完全相同（冷却从断档前最后一个真信号算）。"""
        masked = all_signals(self.panel(self.HOLE), P1)
        blank = self.panel()
        rows = (blank["container"] == "A") & blank["date"].isin([DATES[i] for i in self.HOLE])
        blank.loc[rows, ["state", "z_month"]] = ["NEUTRAL", np.nan]
        pd.testing.assert_frame_equal(masked, all_signals(blank, P1))
        before = all_signals(self.panel(), P1)                            # 断档之前与不标断档时相同
        cut = DATES[min(self.HOLE)]
        pd.testing.assert_frame_equal(masked[masked["date"] < cut].reset_index(drop=True),
                                      before[before["date"] < cut].reset_index(drop=True))

    def test_held_position_rides_through_the_hole(self):
        """已持仓：断档内平盘收盘不跌破止损、不出场；断档结束后第一根真 K 线按正常规则判（跌破 → 次日开盘离场）。"""
        n = 60
        cl = [100.0, 100.0] + [100.0 + k for k in range(1, 11)]          # 入场 100、1R=4，涨到 110 激活，止损 110−6=104
        cl += [110.0] * 30                                                # 断档：平盘 30 行（data_hole = 1）
        cl += [103.0] + [103.0] * (n - len(cl) - 1)                       # 断档后第一根真 K 线 103 < 104
        hole = set(range(12, 42))
        pn = make({"A": cl, "B": flat(n)}, states={"A": {1: "XB"}}, rs={"A": {1: 1}}, holes={"A": hole})
        t = run(pn, n=n).trades.iloc[0]
        self.assertEqual((t["exit_reason"], t["exit_date"]), ("移动止盈", DATES[43]))
        self.assertAlmostEqual(t["mfe_R"], (110 - 100) / 4)                # 断档内止损没动：仍是 104

    def test_panel_without_data_hole_is_rejected(self):
        with self.assertRaisesRegex(PanelError, "data_hole"):
            validate_panel(make({"A": flat(5)}).drop(columns="data_hole"))   # 不默认 0
        bad = make({"A": flat(5)})
        bad["data_hole"] = bad["data_hole"].astype(float)
        bad.loc[0, "data_hole"] = np.nan
        with self.assertRaisesRegex(PanelError, "data_hole"):
            validate_panel(bad)


class HoleDecisionTests(unittest.TestCase):
    """I-26：断档行上一律不做决策，也不作为别人的参照——不成交、不参与排名、不进刻画与零模型。"""
    FLAT = DataHoleTests.FLAT
    HOLE = DataHoleTests.HOLE

    def test_fill_on_a_hole_row_is_skipped_and_the_signal_dropped(self):
        n = 160
        for label, sig, holes in (("build 形状：平盘第 4 行的信号，次日是第 5 行（断档）", 103, self.HOLE),
                                  ("真 K 线的信号，次日直接是断档行", 99, set(range(100, 130)))):
            with self.subTest(label):
                kw = dict(states={"A": {sig: "XB"}}, rs={"A": {sig: 1}})
                pn = make({"A": flat(n), "B": flat(n)}, holes={"A": holes}, **kw)
                res = run(pn, n=n)
                self.assertTrue(res.trades.empty)                                        # 信号不保留：断档后也不补成交
                self.assertEqual(res.skipped[["date", "container", "reason"]].values.tolist(), [[DATES[sig + 1], "A", "数据断档"]])
                t = run(make({"A": flat(n), "B": flat(n)}, **kw), n=n).trades             # 对照：不标断档就照常成交
                self.assertEqual(t["entry_date"].tolist(), [DATES[sig + 1]])

    def test_hole_rows_do_not_take_a_rank(self):
        """11 个容器，断档容器 H 当日 rs 最高：剔掉它，C2 从 3/11 变成 2/10 进前 20%；前 20% 名单与「H 当日不在面板」时相同。"""
        names = ["H"] + [f"C{i}" for i in range(1, 11)]
        rs = {c: {d: 10.0 - k for d in range(3)} for k, c in enumerate(names)}
        pn = make({c: flat(3) for c in names}, rs=rs, holes={"H": {1}})
        p = Params()
        flags = pn.assign(top=rs_top_flags(pn, p)).set_index(["date", "container"])["top"]
        gone = pn[~((pn["container"] == "H") & (pn["date"] == DATES[1]))].reset_index(drop=True)
        ref = gone.assign(top=rs_top_flags(gone, p)).set_index(["date", "container"])["top"]
        pd.testing.assert_series_equal(flags.drop((DATES[1], "H")), ref)
        top = lambda d: sorted(flags[DATES[d]][flags[DATES[d]]].index)                   # noqa: E731
        self.assertEqual((top(0), top(1), top(2)), (["C1", "H"], ["C1", "C2"], ["C1", "H"]))   # 断档只影响那一天
        self.assertFalse(flags[(DATES[1], "H")])
        # 分母：10 个容器、断档容器 H 当日 rs 最低——只排出名次、仍留在分母时 C2 是 2/10 = 20% 会混进前 20%；剔掉后 2/9 不进
        names = [f"C{i}" for i in range(1, 10)] + ["H"]
        rs = {c: {d: 10.0 - k for d in range(3)} for k, c in enumerate(names)}
        pn = make({c: flat(3) for c in names}, rs=rs, holes={"H": {1}})
        flags = pn.assign(top=rs_top_flags(pn, p)).set_index(["date", "container"])["top"]
        gone = pn[~((pn["container"] == "H") & (pn["date"] == DATES[1]))].reset_index(drop=True)
        ref = gone.assign(top=rs_top_flags(gone, p)).set_index(["date", "container"])["top"]
        pd.testing.assert_series_equal(flags.drop((DATES[1], "H")), ref)
        self.assertEqual((top(0), top(1)), (["C1", "C2"], ["C1"]))

    def hole_panel(self, seed=4):
        """8 个随机游走容器；A 在 100–129 平盘（build 形状：104–129 标断档），状态随机，平盘行照样带着可进态。"""
        rng = np.random.default_rng(seed)
        n, names = 260, ["A"] + [f"C{i}" for i in range(7)]
        cl = {c: 100 * np.cumprod(1 + rng.normal(0.0005, 0.012, n)) for c in names}
        cl["A"][100:130] = cl["A"][99]
        st = {c: dict(enumerate(rng.choice(["XB", "NEUTRAL", "EXH", "POP"], n))) for c in names}
        pn = make(cl, st, holes={"A": self.HOLE})
        gone = pn[~((pn["container"] == "A") & pn["date"].isin([DATES[i] for i in self.HOLE]))].reset_index(drop=True)
        unmarked = pn.assign(data_hole=0)
        return pn, gone, unmarked

    def test_characterize_ignores_hole_rows(self):
        pn, gone, unmarked = self.hole_panel()
        p = Params(char_horizon=5, char_bootstrap=200)
        a, b, c = (characterize(x, p, DATES[259]) for x in (pn, gone, unmarked))
        for k in ("by_state", "by_class"):
            pd.testing.assert_frame_equal(a[k], b[k], obj=k)
        self.assertEqual((a["diff_entry_minus_rest"], a["ci95"], a["n_blocks"]), (b["diff_entry_minus_rest"], b["ci95"], b["n_blocks"]))
        self.assertNotEqual(int(c["by_class"]["n"].sum()), int(a["by_class"]["n"].sum()))   # 对照：不排除时样本里有断档行

    def test_null_pool_is_the_strategy_entry_set(self):
        pn, gone, unmarked = self.hole_panel()
        p = Params()
        import src.research.prereg_v1.engine as eng
        seen = []
        real = eng.simulate
        with mock.patch.object(eng, "simulate", side_effect=lambda *a_, **k: seen.append(real(*a_, **k)) or seen[-1]):
            a = random_entry_null(pn, p, DATES[0], DATES[259], n_signals=40, reps=8, seed=3)
        # 夹具自证覆盖了引擎那一半：至少一次随机入场的成交行落在断档上（记「数据断档」），至少一笔 A 的持仓跨过断档
        self.assertTrue(any((r.skipped["reason"] == "数据断档").any() for r in seen))
        lo, hi = DATES[min(self.HOLE)], DATES[max(self.HOLE)]
        self.assertTrue(any(((r.trades["container"] == "A") & (r.trades["entry_date"] < lo) & (r.trades["exit_date"] > hi)).any()
                            for r in seen if len(r.trades)))
        b, c = (random_entry_null(x, p, DATES[0], DATES[259], n_signals=40, reps=8, seed=3) for x in (gone, unmarked))
        np.testing.assert_array_equal(a, b)                                              # 与「断档行不在面板」时逐次相同
        self.assertFalse(np.array_equal(a, c))                                           # 对照：断档行进池，抽样就变了


class HoleExitTests(unittest.TestCase):
    """I-27：断档行对出场也视同无开盘价——exit_flag 保留，顺延到第一个非断档行按其开盘成交。"""
    N = 40

    def trade(self, closes, holes, opens=None):
        pn = make({"A": closes, "B": flat(self.N)}, states={"A": {1: "XB"}}, rs={"A": {1: 1}},
                  opens={"A": opens} if opens else None, holes={"A": holes} if holes else None)
        return run(pn, n=self.N)

    def path(self, breach_day, drop=95.0):
        """进场 100（第 2 天开盘）、1R = 4、止损 96；breach_day 收盘跌到 drop 后一直平；第 21 天开盘 94（断档后第一根真 K 线）。"""
        cl = [100.0] * breach_day + [drop] * (self.N - breach_day)
        op = [cl[0]] + cl[:-1]
        op[21] = 94.0
        return cl, op

    def test_flag_on_a_real_bar_followed_by_a_hole_fills_after_the_hole(self):
        cl, op = self.path(10)
        res = self.trade(cl, set(range(11, 21)), op)
        t = res.trades.iloc[0]
        self.assertEqual((t["exit_date"], t["exit_px"], t["exit_reason"]), (DATES[21], 94.0, "失效位"))
        self.assertEqual(len(res.trades), 1)
        t0 = self.trade(cl, None, op).trades.iloc[0]                                     # 对照：不标断档，次日开盘离场
        self.assertEqual((t0["exit_date"], t0["exit_px"]), (DATES[11], 95.0))
        self.assertEqual(t["mfe_R"], t0["mfe_R"])                                        # 顺延期间不更新最高收盘

    def test_flag_inside_the_hole_fills_after_the_hole(self):
        cl, op = self.path(13)                                                           # 构造：断档行里出现跌破（真实数据里平盘不会跌破）
        res = self.trade(cl, set(range(10, 21)), op)
        t = res.trades.iloc[0]
        self.assertEqual((t["exit_date"], t["exit_px"], t["exit_reason"]), (DATES[21], 94.0, "失效位"))

    def test_without_holes_identical_to_p6e1(self):
        """无断档时与 P6e-1 引擎逐笔相同：随机面板（含偶尔无开盘价的顺延）上的成交、跳过与净值摘要，取自 P6e-1 引擎（main 55ef5db）。"""
        rng = np.random.default_rng(11)
        n, dates = 600, pd.bdate_range("2016-01-01", periods=600)
        rows = []
        for j in range(8):
            c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.013, n))
            o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.003, n))
            o[rng.random(n) < 0.01] = np.nan
            st = rng.choice(["XB", "POP", "BNB", "NEUTRAL", "EXH"], n)
            for i, d in enumerate(dates):
                rows.append(dict(date=d, container=f"C{j}", open=o[i], high=np.nanmax([o[i], c[i]]) * 1.004,
                                 low=np.nanmin([o[i], c[i]]) * 0.996, close=c[i], state=st[i], rs_1m=rng.normal(),
                                 atr20=c[i] * 0.015, z_month=(rng.normal() * 1.5 if d.is_month_end else np.nan), data_hole=0))
        pn = validate_panel(pd.DataFrame(rows))
        res = simulate(pn, Params(), pn["date"].min(), pn["date"].max())
        t = res.trades.copy()
        for col in t.columns:
            if t[col].dtype == float:
                t[col] = t[col].round(10)
        blob = t.to_csv(index=False) + res.skipped.to_csv(index=False) + res.nav.round(10).to_csv()
        self.assertEqual((len(t), len(res.skipped)), (117, 44))
        self.assertEqual(hashlib.sha256(blob.encode()).hexdigest(), "e5988d3d1b31d2a282fbbadb1ff245b0aa1f89756cdd746772b7168f74da5b58")


class EngineTests(unittest.TestCase):
    def single(self, closes, opens=None, atr=2.0, p=None):
        n = len(closes)
        pn = make({"A": closes, "B": flat(n)}, states={"A": {1: "XB"}}, rs={"A": {1: 1}}, atr=atr,
                  opens={"A": opens} if opens else None)
        return run(pn, p, n)

    def test_entry_next_open_and_sizing(self):
        cl = flat(30)
        op = [100.0] * 30
        op[2] = 101.0                                                    # 信号日 1 收盘 100 → 次日开盘 101 成交
        r = self.single(cl, op)
        t = r.trades.iloc[0]
        self.assertEqual(t["entry_date"], DATES[2])
        self.assertAlmostEqual(t["stop_level"], 96.0)
        self.assertAlmostEqual(t["r_unit"], 5.0)
        self.assertAlmostEqual(t["weight"], 0.005 * 101 / 5)            # I-06：1R 恰为 0.5% 净值
        self.assertAlmostEqual(t["init_risk"], 0.005)

    def test_stop_exit_next_open(self):
        cl = flat(30)
        cl[5] = 95.0                                                     # 收盘跌破 96
        op = [100.0] * 30
        op[6] = 94.0
        t = self.single(cl, op).trades.iloc[0]
        self.assertEqual((t["exit_date"], t["exit_reason"]), (DATES[6], "失效位"))
        c = Params().cost_per_side
        self.assertAlmostEqual(t["R"], (94 * (1 - c) - 100 * (1 + c)) / 4.0)
        self.assertLess(t["R"], -1)                                      # 跳空穿过止损，损失 > 1R

    def test_no_stop_trigger_at_equal(self):
        cl = flat(30)
        cl[5] = 96.0                                                     # 收盘等于失效位，不触发（严格跌破）
        self.assertEqual(self.single(cl).trades.iloc[0]["exit_reason"], "期末未平")

    def test_trailing_ratchet(self):
        # 入场 100、1R=4；涨到 110 后激活，止损 = 最高收盘 − 3×ATR(2) = 104；回落到 103 触发
        cl = [100, 100, 102, 104, 106, 110, 108, 107, 103, 103, 103]
        r = self.single(cl)
        t = r.trades.iloc[0]
        self.assertTrue(t["activated"])
        self.assertEqual((t["exit_reason"], t["exit_date"]), ("移动止盈", DATES[9]))
        self.assertAlmostEqual(t["mfe_R"], (110 - 100) / 4)

    def test_trail_only_moves_up(self):
        # 激活后 ATR 变大，止损不下移：108 激活时止损 102，之后 ATR 变 5 → 108−15=93，止损仍 102
        pn = make({"A": [100, 100, 104, 108, 104, 101.5, 101], "B": flat(7)},
                  states={"A": {1: "XB"}}, rs={"A": {1: 1}})
        pn.loc[(pn.container == "A") & (pn.date >= DATES[4]), "atr20"] = 5.0
        t = run(pn, n=7).trades.iloc[0]
        self.assertEqual((t["exit_reason"], t["exit_date"]), ("移动止盈", DATES[6]))

    def test_no_time_limit(self):
        cl = list(np.linspace(100, 300, 380))
        t = self.single(cl).trades.iloc[0]
        self.assertEqual(t["exit_reason"], "期末未平")
        self.assertGreater(t["R"], 40)

    def test_gap_below_stop_skipped(self):
        op = [100.0] * 10
        op[2] = 95.0
        r = self.single(flat(10), op)
        self.assertTrue(r.trades.empty)
        self.assertEqual(r.skipped.iloc[0]["reason"], "开盘已在失效位下方")

    def test_costs_round_trip(self):
        cl = flat(10)
        cl[3] = 95.0
        op = [100.0] * 10
        t = self.single(cl, op).trades.iloc[0]
        c = Params().cost_per_side
        self.assertAlmostEqual(t["R"], (100 * (1 - c) - 100 * (1 + c)) / 4)

    def test_max_positions_and_skipped_logged(self):
        names = [f"C{i}" for i in range(10)]
        p = Params(rs_top_pct=1.0)
        pn = make({c: flat(10) for c in names}, states={c: {1: "BNB"} for c in names},
                  rs={c: {1: float(i)} for i, c in enumerate(names)})
        r = run(pn, p, 10)
        self.assertEqual(len(r.trades), 8)
        self.assertEqual(sorted(r.skipped["container"]), ["C0", "C1"])  # rs 最低的两个排不上
        self.assertTrue((r.skipped["reason"] == "持仓已满").all())

    def test_weight_cap_and_no_leverage(self):
        names = [f"C{i}" for i in range(6)]
        p = Params(rs_top_pct=1.0)
        pn = make({c: flat(10) for c in names}, states={c: {1: "XB"} for c in names},
                  rs={c: {1: float(i)} for i, c in enumerate(names)}, atr=0.1)   # 低波：按风险算会超过 25%
        r = run(pn, p, 10)
        self.assertTrue((r.trades["weight"] <= 0.25 + 1e-12).all())
        self.assertLessEqual(r.invested.max(), 1.0 + 1e-9)
        self.assertEqual(len(r.trades), 4)                                 # 4 × 25% 后现金用尽
        self.assertIn("现金或风险额度不足", set(r.skipped["reason"]))

    def test_already_holding_skipped(self):
        pn = make({"A": flat(30), "B": flat(30)}, states={"A": {1: "XB", 25: "XB"}}, rs={"A": {1: 1, 25: 1}})
        r = run(pn, n=30)
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.skipped.iloc[0]["reason"], "已持有")

    def test_no_lookahead(self):
        rng = np.random.default_rng(1)
        names = [f"C{i}" for i in range(6)]
        cl = {c: 100 * np.cumprod(1 + rng.normal(0, 0.01, 300)) for c in names}
        st = {c: {i: rng.choice(["XB", "BNB", "NEUTRAL", "EXH"]) for i in range(300)} for c in names}
        rs = {c: {i: rng.normal() for i in range(300)} for c in names}
        full = make(cl, st, rs)
        cut = 200
        a = run(full, Params(), 300).trades
        b = run(full[full["date"] <= DATES[cut - 1]], Params(), cut).trades
        key = ["container", "entry_date", "entry_px", "stop_level"]
        a_ = a[a["entry_date"] <= DATES[cut - 1]][key].sort_values(key).reset_index(drop=True)
        self.assertGreater(len(a_), 5)
        self.assertTrue(a_.equals(b[key].sort_values(key).reset_index(drop=True)))        # 截断之后的数据不影响截断前的入场决策
        closed = b[b["exit_reason"] != "期末未平"]
        a_closed = a.merge(closed[key + ["exit_date"]], on=key + ["exit_date"])
        self.assertEqual(len(a_closed), len(closed))                     # 截断前已完成的离场也完全一致

    def test_nav_accounting(self):
        cl = [100, 100, 100, 110, 110]
        r = self.single(cl, p=Params(rs_top_pct=1.0, cost_per_side=0.0))
        w = r.trades.iloc[0]["weight"]
        self.assertAlmostEqual(r.nav.iloc[-1], 1 + w * 0.10)


class NullTests(unittest.TestCase):
    def test_random_entry_null_uses_same_exit_rules(self):
        rng = np.random.default_rng(2)
        names = [f"C{i}" for i in range(6)]
        pn = make({c: 100 * np.cumprod(1 + rng.normal(0, 0.01, 200)) for c in names})
        nr = random_entry_null(pn, Params(), DATES[0], DATES[199], n_signals=30, reps=5, seed=1)
        self.assertEqual(len(nr), 5)
        self.assertTrue(np.isfinite(nr).all())
        nr2 = random_entry_null(pn, Params(), DATES[0], DATES[199], n_signals=30, reps=5, seed=1)
        self.assertTrue(np.array_equal(nr, nr2))                         # 固定种子可复现


class MetricTests(unittest.TestCase):
    def test_drop_best(self):
        t = pd.DataFrame({"R": [10, 5, 1, -1, -1], "exit_reason": ["x"] * 5})
        s = r_stats(t)
        self.assertAlmostEqual(s["mean_R"], 2.8)
        self.assertAlmostEqual(s["mean_R_drop_best_1"], (5 + 1 - 1 - 1) / 4)
        self.assertAlmostEqual(s["mean_R_drop_best_3"], -1.0)

    def test_fragility(self):
        self.assertFalse(is_fragile(0.30, [0.25, 0.20, 0.35, 0.16, 0.40, 0.28]))
        self.assertTrue(is_fragile(0.30, [0.25, 0.10, 0.35, 0.20, 0.40, 0.28]))   # 0.10 < 0.15
        self.assertTrue(is_fragile(0.10, [0.12, -0.01, 0.09, 0.11, 0.08, 0.10]))  # 变号
        self.assertFalse(is_fragile(-0.10, [-0.2, -0.05, -0.1, -0.3, -0.1, -0.1]))

    def test_acceptance(self):
        p = Params()
        yt = pd.DataFrame({"对等权超额": [0.01] * 6 + [-0.01] * 4}, index=list(range(2016, 2026)))
        port = dict(yearly=yt, excess_vs_ew_cagr=0.01, max_dd=-0.2, ew_max_dd=-0.3)
        t = pd.DataFrame({"R": [0.5] * 200 + [-0.4] * 50, "exit_reason": ["x"] * 250})
        acc = acceptance(t, port, p)
        self.assertTrue(acc["v1 成立"], acc)
        port2 = dict(port, max_dd=-0.35)
        self.assertFalse(acceptance(t, port2, p)["v1 成立"])


class CharacterizeTests(unittest.TestCase):
    def test_separable_when_entry_states_lead(self):
        rng = np.random.default_rng(0)
        n, names = 400, [f"C{i}" for i in range(8)]
        cl, st = {}, {}
        for c in names:
            s = rng.choice(["XB", "NEUTRAL", "EXH"], n)
            drift = np.where(s == "XB", 0.004, -0.001)
            r = np.r_[0, drift[:-1]] + rng.normal(0, 0.005, n)          # 可进态之后次日起有正漂移
            cl[c] = 100 * np.cumprod(1 + r)
            st[c] = dict(enumerate(s))
        pn = make(cl, st)
        c = characterize(pn, Params(char_horizon=5, char_bootstrap=300), DATES[n - 1])
        self.assertTrue(c["separable"], c["ci95"])

    def test_not_separable_on_noise(self):
        rng = np.random.default_rng(3)
        n, names = 400, [f"C{i}" for i in range(8)]
        cl = {c: 100 * np.cumprod(1 + rng.normal(0, 0.01, n)) for c in names}
        st = {c: dict(enumerate(rng.choice(["XB", "NEUTRAL", "EXH"], n))) for c in names}
        c = characterize(make(cl, st), Params(char_horizon=5, char_bootstrap=300), DATES[n - 1])
        self.assertFalse(c["separable"], c["ci95"])

    def test_forward_window_stays_in_design(self):
        pn = make({"A": flat(50), "B": flat(50)}, states={"A": {i: "XB" for i in range(50)}})
        c = characterize(pn, Params(char_horizon=20, char_bootstrap=10), DATES[29])
        self.assertEqual(int(c["by_class"]["n"].sum()), 2 * 10)          # 只有前 10 天的 20 日窗口落在截止日内


class CheckTests(unittest.TestCase):
    """run check 的断档段（I-26）：按 build-report 的整段列出，与面板的 data_hole 行数核对，对不上即非 0 退出。"""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td)
        n = 200
        pn = make({"A": flat(n), "B": flat(n)}, holes={"A": DataHoleTests.HOLE})
        b = pd.DataFrame({"date": DATES[:n], "hs300": 3000.0, "hs300_open": 3000.0})
        self.db = self.td / "panel-2026-09-30.sqlite"
        write_panel_db(self.db, pn, b, {})
        self.seg = {"first": str(DATES[100].date()), "last": str(DATES[129].date()), "rows": 30, "trailing": False, "hole_rows": 26}

    def check(self, report=None):
        if report is not None:
            self.db.with_name("panel-2026-09-30.build-report.json").write_text(
                report if isinstance(report, str) else json.dumps(report), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = runner.main(["check", "--panel", str(self.db), "--out", str(self.td / "out")])
        return code, buf.getvalue()

    def test_whole_segments_and_consistency(self):
        code, out = self.check()
        self.assertEqual(code, 0)
        self.assertIn("没有 build-report", out)                                          # 退路：第 5 行起的段
        self.assertIn(str(DATES[104].date()), out)
        code, out = self.check({"containers": {"A": {"stale_runs": [self.seg]}, "B": {}}})
        self.assertEqual(code, 0)
        self.assertIn(f"{DATES[100].date()} {DATES[129].date()}", " ".join(out.split()))  # 整段：从第 1 行平盘起
        self.assertNotIn("对不上", out)
        with mock.patch.object(runner, "OOS_END", str(DATES[110].date())):            # V1 截在断档中间：核对仍用整个面板，不误报
            code, out = self.check()
        self.assertEqual(code, 0)
        self.assertNotIn("对不上", out)
        for bad in ({"containers": {"A": {"stale_runs": [{**self.seg, "hole_rows": 25}]}}},              # 行数不符
                    {"containers": {"A": {"stale_runs": [self.seg]}, "Z": {"stale_runs": [self.seg]}}}):  # 报告有、面板没有的容器
            code, out = self.check(bad)
            self.assertEqual(code, 1)
            self.assertIn("对不上", out)
        for broken in ("{not json", json.dumps({"containers": []}), json.dumps({"containers": {"A": {"stale_runs": [{"first": "x"}]}}})):
            code, out = self.check(broken)
            self.assertEqual(code, 2)
            self.assertIn("读不懂", out)


class RunnerTests(unittest.TestCase):
    def test_oos_runs_only_once_and_steps_in_order(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            dates = pd.bdate_range("2014-01-01", "2016-06-30")
            rng = np.random.default_rng(5)
            rows = []
            for c in ["A", "B", "C", "D", "E"]:
                cl = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(dates)))
                for i, d in enumerate(dates):
                    rows.append(dict(date=d, container=c, open=cl[i - 1] if i else cl[0], high=cl[i] * 1.01, low=cl[i] * 0.99,
                                     close=cl[i], state=rng.choice(["XB", "NEUTRAL"]), rs_1m=rng.normal(), atr20=cl[i] * 0.01,
                                     z_month=np.nan, data_hole=0))
            df = pd.DataFrame(rows)
            df["high"] = df[["open", "high", "close"]].max(axis=1)
            df["low"] = df[["open", "low", "close"]].min(axis=1)
            hs = np.linspace(3000, 3300, len(dates))
            write_panel_db(td / "panel.sqlite", df, pd.DataFrame({"date": dates, "hs300": hs, "hs300_open": hs}), {})
            args = ["--panel", str(td / "panel.sqlite"), "--out", str(td / "out")]           # --bench 默认同一个库
            self.assertEqual(runner.main(["oos"] + args), 2)                # 没刻画不许跑
            self.assertEqual(runner.main(["characterize"] + args), 0)
            if (td / "out" / "STOP").exists():
                self.assertEqual(runner.main(["design"] + args), 2)         # 分不开就停
                (td / "out" / "STOP").unlink()
            self.assertEqual(runner.main(["oos"] + args), 2)                # 没设计期检查不许跑
            self.assertEqual(runner.main(["design"] + args), 0)
            self.assertEqual(runner.main(["oos"] + args), 0)
            self.assertEqual(runner.main(["oos"] + args), 3)                # 第二次被锁拒绝
            self.assertTrue((td / "out" / "OOS_LOCK.json").exists())
            lock = json.loads((td / "out" / "OOS_LOCK.json").read_text())
            self.assertEqual(lock["panel_sha256"], lock["bench_sha256"])
            from src.research.prereg_v1.panel import content_sha256
            self.assertEqual(lock["panel_content_sha256"], content_sha256(td / "panel.sqlite"))     # 跨机器可复现的数据指纹


if __name__ == "__main__":
    unittest.main()
