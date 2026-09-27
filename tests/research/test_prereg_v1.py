"""prereg-v1 框架的规则测试。只用构造数据，不接触任何真实行情。

运行：python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.research.prereg_v1 import run as runner                          # noqa: E402
from src.research.prereg_v1.characterize import characterize               # noqa: E402
from src.research.prereg_v1.config import Params                           # noqa: E402
from src.research.prereg_v1.engine import random_entry_null, simulate      # noqa: E402
from src.research.prereg_v1.metrics import acceptance, r_stats             # noqa: E402
from src.research.prereg_v1.panel import (PanelError, ew_daily_returns,    # noqa: E402
                                          reference_atr, validate_panel)
from src.research.prereg_v1.signals import all_signals, breakout_signals   # noqa: E402

DATES = pd.bdate_range("2020-01-01", periods=400)
P1 = Params(rs_top_pct=1.0)          # 与相对强弱无关的测试：放开前 20% 门槛，只测其余规则


def make(closes: dict, states: dict = None, rs: dict = None, atr: float = 2.0, opens: dict = None, z: dict = None):
    """closes: 容器 → 收盘序列；opens 默认等于前一日收盘；states/rs/z: 容器 → {日序号: 值}。"""
    rows = []
    for c, cl in closes.items():
        cl = np.asarray(cl, float)
        op = np.r_[cl[0], cl[:-1]] if not opens or c not in opens else np.asarray(opens[c], float)
        for i, d in enumerate(DATES[: len(cl)]):
            o, x = op[i], cl[i]
            rows.append(dict(date=d, container=c, open=o, high=max(o, x) + 0.1, low=min(o, x) - 0.1, close=x,
                             state=(states or {}).get(c, {}).get(i, "NEUTRAL"),
                             rs_1m=(rs or {}).get(c, {}).get(i, 0.0), atr20=atr,
                             z_month=(z or {}).get(c, {}).get(i, np.nan)))
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
                                     z_month=np.nan))
            df = pd.DataFrame(rows)
            df["high"] = df[["open", "high", "close"]].max(axis=1)
            df["low"] = df[["open", "low", "close"]].min(axis=1)
            df.to_csv(td / "panel.csv", index=False)
            pd.DataFrame({"date": dates, "hs300": np.linspace(3000, 3300, len(dates))}).to_csv(td / "bench.csv", index=False)
            args = ["--panel", str(td / "panel.csv"), "--bench", str(td / "bench.csv"), "--out", str(td / "out")]
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


if __name__ == "__main__":
    unittest.main()
