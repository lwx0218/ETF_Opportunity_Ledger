"""每日任务骨架：构造面板逐日回放，只验流程（立卡 → 次日进场 / 作废 → 每日行 → 移动止盈离场 → 跟踪期满）与幂等、无未来。

运行：python -m unittest discover -s tests -t .
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import tests  # noqa: E402,F401 — 置位 ETF_LEDGER_TESTING：直接当脚本跑时也只许连临时库

from src.jobs import rules as R                                  # noqa: E402
from src.jobs.__main__ import main as jobs_main                  # noqa: E402
from src.jobs.daily import DailyJob, next_weekday_open           # noqa: E402
from src.jobs.ew import EwStore                                  # noqa: E402
from src.jobs.guard import preflight                             # noqa: E402
from src.jobs.live import live_panel                             # noqa: E402
from src.indicators.build import container_panel, write_panel_db  # noqa: E402
from src.ledger.store import Ledger, LedgerError                 # noqa: E402
from src.research.prereg_v1.engine import simulate              # noqa: E402
from src.research.prereg_v1.config import Params                 # noqa: E402
from tests.marketdb import open_db, put, put_coverage             # noqa: E402

DAYS = [d.date().isoformat() for d in pd.bdate_range("2026-01-02", "2026-04-30")]
SIGNAL = "2026-01-30"                      # 月末
RULES = {"恐慌下轨": dict(R.RULE_R), "事件驱动": {}}                 # = load_rule_config 对启用配置的返回
CONFIG = {"confirmed_terms": R.TERMS_VERSION, "恐慌下轨": {"enabled": True, **R.RULE_R}, "事件驱动": {"enabled": True}}
EVENT_EXP = {"horizon_days": 20, "target_excess_pct": 3.0, "benchmark": "沪深300"}
INST = {"半导体": {"code": "512480", "name": "国联安中证全指半导体ETF", "research_code": "H30184CNY010"},
        "黄金": {"code": "518880", "name": "华安黄金易ETF", "research_code": "518880"},
        "沪深300": {"code": "510300", "name": "华泰柏瑞沪深300ETF", "research_code": "H00300"}}


def semis_path() -> list[float]:
    """信号日前平在 100；次日开盘 100.5 进场；十天涨到 110（启用移动止盈，止损 104）；随后跌破 104 → 次日开盘离场。"""
    i0 = DAYS.index(SIGNAL)
    c = [100.0] * (i0 + 1)
    c += [100.5 + k for k in range(10)]          # 100.5 … 109.5
    c += [110.0, 108.0, 106.0, 103.5]             # 103.5 < 104 → 离场信号
    c += [103.0 + 0.1 * k for k in range(len(DAYS) - len(c))]
    return c


def make_panel(extra: dict | None = None, semis: list[float] | None = None, semis_open: dict | None = None
               ) -> tuple[pd.DataFrame, pd.Series]:
    """semis 换掉半导体的收盘路径；semis_open {日期: 开盘} 覆盖半导体个别日子的开盘（默认 = 前收）。"""
    rows = []
    series = {"半导体": semis or semis_path(), "黄金": [300 + 0.2 * k for k in range(len(DAYS))],
              "沪深300": [4000 + k for k in range(len(DAYS))]}
    for name, closes in series.items():
        for k, d in enumerate(DAYS):
            cl = closes[k]
            op = closes[k - 1] if k else cl
            if name == "半导体" and d == DAYS[DAYS.index(SIGNAL) + 1]:
                op = 100.5
            if name == "半导体" and d in (semis_open or {}):
                op = semis_open[d]
            rows.append(dict(date=pd.Timestamp(d), container=name, open=op, high=max(op, cl) + 0.5, low=min(op, cl) - 0.5,
                             close=cl, state="NEUTRAL", rs_1m=0.01 * (k % 7) - (0.02 if name == "黄金" else 0), atr20=2.0,
                             z_month=np.nan, data_hole=0))
    p = pd.DataFrame(rows)
    p.loc[(p["container"] == "半导体") & (p["date"] == pd.Timestamp(SIGNAL)), "z_month"] = -2.5
    for (name, d), z in (extra or {}).items():
        p.loc[(p["container"] == name) & (p["date"] == pd.Timestamp(d)), "z_month"] = z
    bench = p[p["container"] == "沪深300"].set_index("date")["close"]
    return p, bench


def dump(L: Ledger) -> dict:
    tables = ("cards", "evidence", "strength_scores", "entries", "daily", "exit_signals", "exits", "finals", "voids", "ew_daily")
    return {t: [tuple(r) for r in L.conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in tables}


class Replay(unittest.TestCase):
    def setUp(self):
        self.now = ""
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.new_ledger()

    def new_ledger(self):
        """新建台账库（等权日收益在库内的 ew_daily 表，与台账天然成对）。"""
        if getattr(self, "L", None):
            self.L.close()
        self.L = Ledger(":memory:", clock=lambda: self.now, replay=True)
        self.addCleanup(self.L.close)

    def replay(self, panel, bench, days=DAYS, truncate=False, p=Params(), events_dir=None, **kw):
        reps = []
        job = None if truncate else DailyJob(self.L, panel, bench, rules=RULES, instruments=INST, p=p, events_dir=events_dir, **kw)
        for d in days:
            self.now = f"{d}T16:00"
            if truncate:                     # 每天只给当天及以前的数据（沪深300 开盘价也截断）
                cut = pd.Timestamp(d)
                kw_cut = {**kw, **({"bench_open": kw["bench_open"][kw["bench_open"].index <= cut]} if "bench_open" in kw else {})}
                job = DailyJob(self.L, panel[panel["date"] <= cut], bench[bench.index <= cut], rules=RULES, instruments=INST, p=p,
                               events_dir=events_dir, **kw_cut)
            reps.append(job.run(d))
        return reps

    def test_full_lifecycle(self):
        panel, bench = make_panel()
        reps = {r.day: r for r in self.replay(panel, bench)}
        cid = "T-2026-001"
        self.assertEqual(reps[SIGNAL].created, [cid])
        card = self.L.card(cid)
        self.assertEqual((card["trigger_type"], card["invalidation_price"], card["r_unit_per_share"], card["owner_score_deadline"]),
                         ("恐慌下轨", 96.0, 4.0, "2026-02-02T09:30"))
        # v1.1-a / v1.1-c：机械卡未检索、不写 agent 分；评分菜单第 2 项
        self.assertEqual((card["evidence_status"], card["scoring_rule"], card["expectation_horizon_days"],
                          card["expectation_target_excess_pct"], card["expectation_target_r"], card["expectation_benchmark"]),
                         ("未检索", "schema-v1.1-R", None, None, 2, "等权组合"))
        self.assertEqual(self.L.conn.execute("SELECT count(*) FROM strength_scores WHERE card_id = ?", (cid,)).fetchone()[0], 0)
        self.assertEqual(self.L.evidence(cid), [])
        self.assertEqual(reps["2026-02-02"].entries, [cid])
        e = dict(self.L.conn.execute("SELECT * FROM entries WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual((e["entry_date"], e["entry_price"]), ("2026-02-02", 100.5))
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
        i_breach = DAYS.index("2026-02-02") + 13                       # 103.5 那天
        self.assertEqual((x["exit_date"], x["exit_reason"]), (DAYS[i_breach + 1], "移动止盈"))
        self.assertAlmostEqual(x["exit_price"], 103.5)
        self.assertEqual(x["exit_signal_close"], 103.5)                   # v1.1-f：触发出场的那根收盘（跌破 104 的那天），不低于失效位 96
        self.assertAlmostEqual(x["realized_r"], (103.5 * (1 - 0.0005) - 100.5 * (1 + 0.0005)) / 4.5, places=6)
        rows = self.L.daily_rows(cid)
        stops = [r["stop_now"] for r in rows if r["stop_now"] is not None]
        self.assertEqual(stops, sorted(stops))                          # 止损只上不下
        self.assertAlmostEqual(max(stops), 104.0)
        # v1.1-e：超额 = 含成本的持有收益 − 等权基准同窗口（等权没有开盘点位 → 前一日收盘到前一日收盘）
        ew = EwStore(self.L).series()
        self.assertAlmostEqual(card["cf_ew_level"], ew[pd.Timestamp(SIGNAL)])
        prev_exit = DAYS[DAYS.index(x["exit_date"]) - 1]
        held = 103.5 * (1 - 0.0005) / (100.5 * (1 + 0.0005)) - 1
        self.assertAlmostEqual(x["realized_excess_pct"], (held - (ew[pd.Timestamp(prev_exit)] / ew[pd.Timestamp(SIGNAL)] - 1)) * 100,
                               places=5)
        f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual(self.L.status(cid), "已结")
        self.assertEqual(f["final_score"], "部分")                      # 0 < realized_r ≈ 0.64 < 2（菜单第 2 项）
        self.assertEqual(self.L.summary()["denominator"], 1)

    def falsify_path(self, tail: list[float], gap_open: float) -> dict:
        """信号日 100 → 次日开盘 100.5 进场 → tail 的收盘，最后一根触发离场 → 次日开盘 gap_open（高开）。返回出场与期满记录。"""
        i0 = DAYS.index(SIGNAL)
        c = [100.0] * (i0 + 1) + tail
        exit_day = DAYS[len(c)]
        c += [gap_open + 0.05 * k for k in range(len(DAYS) - len(c))]
        panel, bench = make_panel(semis=c, semis_open={exit_day: gap_open})
        self.replay(panel, bench)
        cid = "T-2026-001"
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
        f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual((x["exit_date"], x["exit_price"], x["exit_signal_close"]), (exit_day, gap_open, tail[-1]))
        return x | f

    def test_stop_exit_with_gap_up_is_falsified(self):
        """v1.1-f 端到端：收盘跌破失效位 96 → 次日高开 97 离场，−1 < R < 0；旧口径（R ≤ −1 才证伪）会记未达。"""
        r = self.falsify_path([100.5, 101.0, 100.0, 95.5], gap_open=97.0)
        self.assertEqual(r["exit_reason"], "失效位")
        self.assertTrue(-1 < r["realized_r"] < 0)
        self.assertEqual(r["final_score"], "证伪")

    def test_trailing_exit_below_the_locked_line_is_falsified(self):
        """激活移动止盈后单日暴跌到 90（< 锁定失效位 96）→ 标签是移动止盈，按锁定字段判证伪；次日高开 99，R ≈ −0.36。"""
        r = self.falsify_path([100.5 + k for k in range(6)] + [90.0], gap_open=99.0)
        self.assertEqual(r["exit_reason"], "移动止盈")
        self.assertTrue(-1 < r["realized_r"] < 0)
        self.assertEqual(r["final_score"], "证伪")

    def deferred_path(self, tail: list[float], after: list[float], opens: dict) -> tuple[pd.DataFrame, pd.Series]:
        """信号日 100 → 次日开盘 100.5 进场 → tail（最后一根跌破止损）→ after 的收盘；opens {相对 tail 末根的天数: 开盘}，NaN = 没有开盘价。"""
        i0 = DAYS.index(SIGNAL)
        c = [100.0] * (i0 + 1) + tail
        b = len(c) - 1
        c += after + [after[-1]] * (len(DAYS) - len(c) - len(after))
        return make_panel(semis=c, semis_open={DAYS[b + k]: v for k, v in opens.items()}), b

    def engine_exit(self, panel) -> tuple:
        """同一组构造数据交给 V1 引擎（prereg_v1.engine.simulate），只给 01-30 那一个信号。"""
        sig = pd.DataFrame([dict(date=pd.Timestamp(SIGNAL), container="半导体", branch="恐慌", state="NEUTRAL", close=100.0, atr20=2.0,
                                 rs_1m=0.0, z_month=-2.5, stop_level=96.0, priority=0.0)])
        t = simulate(panel, Params(), DAYS[0], DAYS[-1], signals=sig).trades.iloc[0]
        return t["exit_date"].date().isoformat(), float(t["exit_px"]), t["exit_reason"]

    def test_deferred_exit_is_not_cancelled(self):
        """v1.1-g 第 3 条：跌破失效位次日没有开盘价、当天收盘回到止损之上 → 信号不撤销，第三天开盘仍出场，触发收盘是跌破那一行。"""
        (panel, bench), b = self.deferred_path([100.5, 101.0, 100.0, 95.5], [97.0, 97.5], {1: np.nan, 2: 97.2})
        reps = {r.day: r for r in self.replay(panel, bench)}
        cid = "T-2026-001"
        sig = self.L.exit_signal(cid)
        self.assertEqual((sig["signal_date"], sig["reason"], sig["signal_close"]), (DAYS[b], "失效位", 95.5))
        self.assertEqual(reps[DAYS[b]].signals, [cid])
        self.assertTrue(any("顺延" in x for x in reps[DAYS[b + 1]].skipped))
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual((x["exit_date"], x["exit_price"], x["exit_reason"], x["exit_signal_close"]), (DAYS[b + 2], 97.2, "失效位", 95.5))
        self.assertEqual(self.engine_exit(panel), (DAYS[b + 2], 97.2, "失效位"))              # 与 V1 引擎同一出场日与价格
        f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual(f["final_score"], "证伪")                                             # 95.5 < 锁定失效位 96

    def test_trailing_stop_frozen_while_exit_is_pending(self):
        """激活后跌破移动止损 → 次日没有开盘价、收盘大涨：止损不跟着上移，第三天开盘照常出场。"""
        tail = [100.5 + k for k in range(6)] + [99.0]                    # 105.5 激活，止损 105.5 − 3×2 = 99.5；99.0 跌破
        (panel, bench), b = self.deferred_path(tail, [106.0, 106.5], {1: np.nan, 2: 105.0})
        self.replay(panel, bench)
        cid = "T-2026-001"
        rows = {r["date"]: r for r in self.L.daily_rows(cid)}
        self.assertAlmostEqual(rows[DAYS[b]]["stop_now"], 99.5)
        self.assertAlmostEqual(rows[DAYS[b + 1]]["stop_now"], 99.5)                             # 106 收盘不再把止损抬到 100
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual((x["exit_date"], x["exit_price"], x["exit_reason"], x["exit_signal_close"]), (DAYS[b + 2], 105.0, "移动止盈", 99.0))
        self.assertEqual(self.engine_exit(panel), (DAYS[b + 2], 105.0, "移动止盈"))

    def test_deferred_path_rerun_and_truncation(self):
        """顺延路径上：同日重跑不变；逐日只给 ≤ D 的数据回放，与全量逐表相同（含出场信号表）。"""
        (panel, bench), b = self.deferred_path([100.5, 101.0, 100.0, 95.5], [97.0, 97.5], {1: np.nan, 2: 97.2})
        self.replay(panel, bench)
        full = dump(self.L)
        self.assertTrue(full["exit_signals"])
        again = self.replay(panel, bench)
        self.assertFalse(any(r.changed() for r in again))
        self.assertEqual(dump(self.L), full)
        self.new_ledger()
        self.replay(panel, bench, truncate=True)
        self.assertEqual(dump(self.L), full)                             # 含 ew_daily：等权日收益逐日追加，与一次给全数据相同

    def test_crash_between_daily_row_and_signal_loses_nothing(self):
        """每日行与出场信号同一事务：写信号时崩溃 → 两者都没写；同一天重跑补齐，次日照常出场（与引擎一致）。"""
        (panel, bench), b = self.deferred_path([100.5, 101.0, 100.0, 95.5], [97.0, 97.5], {})
        job = DailyJob(self.L, panel, bench, rules=RULES, instruments=INST)
        orig = Ledger._insert

        def boom(L, table, row, stamp=True):
            if table == "exit_signals":
                raise KeyboardInterrupt("模拟写信号时进程被杀")
            return orig(L, table, row, stamp)
        for d in DAYS[: b + 1]:
            self.now = f"{d}T16:00"
            if d == DAYS[b]:
                with mock.patch.object(Ledger, "_insert", boom), self.assertRaises(KeyboardInterrupt):
                    job.run(d)
                self.assertNotIn(DAYS[b], [r["date"] for r in self.L.daily_rows("T-2026-001")])   # 当天行也没留下
                self.assertIsNone(self.L.exit_signal("T-2026-001"))
            rep = job.run(d)
        self.assertEqual(rep.signals, ["T-2026-001"])                                          # 重跑：行与信号一起写
        for d in DAYS[b + 1:]:
            self.now = f"{d}T16:00"
            job.run(d)
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
        self.assertEqual(self.engine_exit(panel), (x["exit_date"], x["exit_price"], x["exit_reason"]))

    def test_missing_row_defers_and_pending_at_end_stays(self):
        """跌破次日该容器整行缺失 → 顺延；数据到期末都没有开盘价 → 信号保留、不出场（引擎记「期末未平」）。"""
        (panel, bench), b = self.deferred_path([100.5, 101.0, 100.0, 95.5], [97.0, 97.5], {})
        gone = panel[~((panel["container"] == "半导体") & (panel["date"] == pd.Timestamp(DAYS[b + 1])))]
        self.replay(gone, bench)
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
        self.assertEqual((x["exit_date"], x["exit_signal_close"]), (DAYS[b + 2], 95.5))
        self.assertEqual(self.engine_exit(gone)[:2], (x["exit_date"], x["exit_price"]))
        self.new_ledger()
        late = panel.copy()
        late.loc[(late["container"] == "半导体") & (late["date"] > pd.Timestamp(DAYS[b])), "open"] = np.nan
        self.replay(late, bench)
        self.assertEqual(self.L.status("T-2026-001"), "当下")
        self.assertEqual(self.L.exit_signal("T-2026-001")["signal_date"], DAYS[b])
        self.assertEqual(self.engine_exit(late)[2], "期末未平")

    def test_mfe_frozen_after_the_signal_matches_the_engine(self):
        """v1.1-h 第 1 条：跌破失效位次日没有开盘价、当天收盘创新高（103 > 此前最高 101）→ 顺延期间 MFE / MAE 不变，
        出场时的 MFE 等于引擎的 mfe_R（引擎在 exit_flag 之后不再更新 hi_close）；信号日那一行照常按当天收盘更新。"""
        (lp, lb), _ = self.deferred_path([100.5, 101.0, 100.0, 95.5], [90.0, 97.5], {1: np.nan, 2: 97.2})
        self.replay(lp, lb)                                                                      # 顺延日收盘创新低：MAE 也不动
        lows = self.L.daily_rows("T-2026-001")
        sig_low = next(r for r in lows if r["close"] == 95.5)
        deferred_low = next(r for r in lows if r["close"] == 90.0)
        self.assertLess(deferred_low["r_current"], sig_low["mae"])
        self.assertEqual((deferred_low["mfe"], deferred_low["mae"]), (sig_low["mfe"], sig_low["mae"]))
        self.assertAlmostEqual(sig_low["mae"], sig_low["r_current"], places=6)                 # 信号日那一行：MAE 取到当天的跌破收盘
        self.new_ledger()
        (panel, bench), b = self.deferred_path([100.5, 101.0, 100.0, 95.5], [103.0, 97.5], {1: np.nan, 2: 97.2})
        self.replay(panel, bench)
        cid = "T-2026-001"
        rows = {r["date"]: r for r in self.L.daily_rows(cid)}
        sig, deferred, fill = rows[DAYS[b]], rows[DAYS[b + 1]], rows[DAYS[b + 2]]
        self.assertEqual(deferred["close"], 103.0)
        self.assertGreater(deferred["r_current"], sig["mfe"])                                  # 收盘创新高……
        self.assertEqual((deferred["mfe"], deferred["mae"]), (sig["mfe"], sig["mae"]))         # ……MFE / MAE 不动
        self.assertEqual((fill["mfe"], fill["mae"]), (sig["mfe"], sig["mae"]))
        engine = simulate(panel, Params(), DAYS[0], DAYS[-1], signals=self.engine_signal()).trades.iloc[0]
        self.assertEqual(engine["exit_date"].date().isoformat(), DAYS[b + 2])
        self.assertAlmostEqual(sig["mfe"], engine["mfe_R"], places=6)
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual((x["exit_date"], x["exit_price"], x["exit_reason"]), (DAYS[b + 2], 97.2, "失效位"))

    def engine_signal(self):
        return pd.DataFrame([dict(date=pd.Timestamp(SIGNAL), container="半导体", branch="恐慌", state="NEUTRAL", close=100.0, atr20=2.0,
                                  rs_1m=0.0, z_month=-2.5, stop_level=96.0, priority=0.0)])

    def test_same_day_thesis_void_overrides_the_job_stop_signal(self):
        """v1.1-h 第 4 条：每日任务在跌破那天收盘后写「移动止盈」信号；owner 同一信号日声明「论点作废」——
        成交日 09:30 前声明则出场引用它、评分证伪（R > 0 也一样）；09:30 起声明的不生效，照止损出场。"""
        panel, bench = make_panel()
        i_breach = DAYS.index("2026-02-02") + 13
        for when, want_reason, want_score in ((f"{DAYS[i_breach]}T20:00", "论点作废", "证伪"),
                                              (f"{DAYS[i_breach + 1]}T10:00", "移动止盈", "部分")):
            with self.subTest(when):
                self.new_ledger()
                self.replay(panel, bench, days=DAYS[: i_breach + 1])
                cid = "T-2026-001"
                self.assertEqual(self.L.exit_signal(cid)["reason"], "移动止盈")
                self.now = when
                self.L.signal_exit(cid, DAYS[i_breach], "论点作废", 103.5)
                self.replay(panel, bench, days=DAYS[i_breach + 1:])
                x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
                self.assertEqual((x["exit_date"], x["exit_reason"], x["exit_signal_close"]), (DAYS[i_breach + 1], want_reason, 103.5))
                self.assertGreater(x["realized_r"], 0)
                f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = ?", (cid,)).fetchone())
                self.assertEqual(f["final_score"], want_score)

    def test_hole_on_the_fill_day_voids_the_card_like_the_engine_skips(self):
        """I-26：候选卡的成交日是数据断档 → 作废「数据断档」（留在分母），与 V1 引擎记 skipped「数据断档」对拍；
        恐慌规则不看断档行：断档行上的月末 z ≤ −2 不立卡。"""
        panel, bench = make_panel({("黄金", "2026-02-27"): -3.0})
        fill = DAYS[DAYS.index(SIGNAL) + 1]
        holed = panel.copy()
        holed.loc[(holed["container"] == "半导体") & (holed["date"] == pd.Timestamp(fill)), "data_hole"] = 1
        holed.loc[(holed["container"] == "黄金") & (holed["date"] == pd.Timestamp("2026-02-27")), "data_hole"] = 1
        reps = {r.day: r for r in self.replay(holed, bench)}
        self.assertEqual(reps[fill].voids, [("T-2026-001", "数据断档")])
        self.assertEqual(self.L.status("T-2026-001"), "作废")
        self.assertEqual(reps["2026-02-27"].created, [])                                      # 断档行上的 z 不立卡
        self.assertEqual(self.L.summary()["denominator"], 1)
        res = simulate(holed, Params(), DAYS[0], DAYS[-1], signals=self.engine_signal())
        self.assertTrue(res.trades.empty)
        self.assertEqual(res.skipped[["date", "container", "reason"]].values.tolist(), [[pd.Timestamp(fill), "半导体", "数据断档"]])
        self.new_ledger()                                                                    # 对照：不标断档照常进场、照常立卡
        reps = {r.day: r for r in self.replay(panel, bench)}
        self.assertEqual(reps[fill].entries, ["T-2026-001"])
        self.assertEqual(reps["2026-02-27"].created, ["T-2026-002"])

    def test_hole_does_not_jump_the_skip_order(self):
        """I-26 的「数据断档」排在已持有、持仓已满之后（与引擎同一位置）：两种情况下作废原因与引擎 skipped 一致。"""
        flat = [100.0] * len(DAYS)                                                            # 半导体不跌破：第一张卡一直持有
        panel, bench = make_panel({("半导体", "2026-02-27"): -2.5}, semis=flat)
        panel.loc[(panel["container"] == "半导体") & (panel["date"] == pd.Timestamp("2026-03-02")), "data_hole"] = 1
        reps = {r.day: r for r in self.replay(panel, bench)}
        self.assertEqual(reps["2026-03-02"].voids, [("T-2026-002", "已持有该容器（不加仓，I-09）")])
        two = pd.concat([self.engine_signal(), self.engine_signal().assign(date=pd.Timestamp("2026-02-27"), z_month=-2.5)])
        res = simulate(panel, Params(), DAYS[0], DAYS[-1], signals=two)
        self.assertEqual(res.skipped["reason"].tolist(), ["已持有"])
        self.new_ledger()                                                                     # 持仓已满 + 断档：仍记「持仓已满」
        panel, bench = make_panel({("黄金", SIGNAL): -2.2})
        fill = DAYS[DAYS.index(SIGNAL) + 1]
        panel.loc[(panel["container"] == "黄金") & (panel["date"] == pd.Timestamp(fill)), "data_hole"] = 1
        reps = {r.day: r for r in self.replay(panel, bench, days=DAYS[:30], p=Params(max_positions=1))}
        self.assertEqual(reps[fill].voids, [("T-2026-002", "持仓已满")])
        gold = self.engine_signal().assign(container="黄金", close=float(panel.loc[(panel["container"] == "黄金")
                                                                                    & (panel["date"] == pd.Timestamp(SIGNAL)), "close"].iloc[0]),
                                           z_month=-2.2, priority=1.0)
        gold["stop_level"] = gold["close"] - 4.0
        res = simulate(panel, Params(max_positions=1), DAYS[0], DAYS[29], signals=pd.concat([self.engine_signal(), gold]))
        self.assertEqual(res.skipped[["container", "reason"]].values.tolist(), [["黄金", "持仓已满"]])

    def test_late_manual_signal_uses_the_next_close(self):
        """v1.1-i 第 1 条：X+1 09:31 补记 X 日的手动信号被拒（存储层），只能用 X+1 的收盘作信号行，X+2 开盘成交；09:29 记的照常 X+1 开盘成交。"""
        panel, bench = make_panel(semis=[100.0 + 0.01 * k for k in range(len(DAYS))])
        i = DAYS.index("2026-02-10")
        for when, signal_day, fill_day in (("T09:31", DAYS[i + 1], DAYS[i + 2]), ("T09:29", DAYS[i], DAYS[i + 1])):
            with self.subTest(when):
                self.new_ledger()
                self.replay(panel, bench, days=DAYS[: i + 1])
                self.now = f"{DAYS[i + 1]}{when}"
                if when == "T09:31":
                    with self.assertRaisesRegex(LedgerError, "09:30 前记录"):
                        self.L.signal_exit("T-2026-001", DAYS[i], "手动", self.L.daily_rows("T-2026-001")[-1]["close"], "收盘后没来得及")
                    self.replay(panel, bench, days=[DAYS[i + 1]])
                    self.now = f"{DAYS[i + 1]}T20:00"                                         # 改用 X+1 的收盘
                close = next(r["close"] for r in self.L.daily_rows("T-2026-001") if r["date"] == signal_day)
                self.L.signal_exit("T-2026-001", signal_day, "手动", close, "收盘后决定")
                self.replay(panel, bench, days=DAYS[i + 1: i + 3] if when == "T09:29" else [DAYS[i + 2]])
                x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
                self.assertEqual((x["exit_date"], x["exit_reason"], x["exit_signal_close"]), (fill_day, "手动", close))

    def test_stop_during_a_hole_fills_after_it_like_the_engine(self):
        """I-27 / v1.1-i 第 3 条：跌破失效位后接着 3 行断档（开盘是陈旧拷贝）→ 出场信号保留，断档后第一根真 K 线开盘成交；
        与 V1 引擎逐项相同（出场日、价、原因、R、MFE），顺延期间 MFE / MAE 冻结。"""
        (panel, bench), b = self.deferred_path([100.5, 101.0, 100.0, 95.5], [95.5, 95.5, 95.5, 97.0, 97.5], {4: 96.8})
        for k in (1, 2, 3):
            panel.loc[(panel["container"] == "半导体") & (panel["date"] == pd.Timestamp(DAYS[b + k])), "data_hole"] = 1
        reps = {r.day: r for r in self.replay(panel, bench)}
        self.assertTrue(all(any("数据断档，顺延" in x for x in reps[DAYS[b + k]].skipped) for k in (1, 2, 3)))
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
        t = simulate(panel, Params(), DAYS[0], DAYS[-1], signals=self.engine_signal()).trades.iloc[0]
        self.assertEqual((x["exit_date"], x["exit_price"], x["exit_reason"]), (DAYS[b + 4], 96.8, "失效位"))
        self.assertEqual((t["exit_date"].date().isoformat(), t["exit_px"], t["exit_reason"]), (x["exit_date"], x["exit_price"], x["exit_reason"]))
        self.assertAlmostEqual(x["realized_r"], t["R"], places=6)
        rows = self.L.daily_rows("T-2026-001")
        sig = next(r for r in rows if r["date"] == DAYS[b])
        self.assertAlmostEqual(sig["mfe"], t["mfe_R"], places=6)
        self.assertTrue(all((r["mfe"], r["mae"]) == (sig["mfe"], sig["mae"]) for r in rows if DAYS[b] < r["date"] <= DAYS[b + 4]))
        self.new_ledger()                                                                    # 对照：不标断档，次日开盘离场（与 P6e-2 相同）
        self.replay(panel.assign(data_hole=0), bench)
        x0 = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
        self.assertEqual(x0["exit_date"], DAYS[b + 1])

    def test_hole_container_does_not_take_a_rank(self):
        """v1.1-i 第 4 条（P6e-2 复核的半导体用例）：断档容器的陈旧 rs_1m 很高也不挤占名次——每日行的 rs_1m_rank
        与立卡时冻结的 crowd_rs_1m_rank 都不受它影响；断档容器自己的名次为空。"""
        d = DAYS[DAYS.index(SIGNAL) + 3]
        panel, bench = make_panel()
        for day in (SIGNAL, d):
            row = (panel["container"] == "黄金") & (panel["date"] == pd.Timestamp(day))
            panel.loc[row, ["rs_1m", "data_hole"]] = [0.5, 1]
        self.replay(panel, bench, days=DAYS[: DAYS.index(d) + 1])
        self.assertEqual(self.L.card("T-2026-001")["crowd_rs_1m_rank"], 1)
        row = next(r for r in self.L.daily_rows("T-2026-001") if r["date"] == d)
        self.assertEqual(row["rs_1m_rank"], 1)
        today = panel[panel["date"] == pd.Timestamp(d)]
        self.assertTrue(np.isnan(DailyJob._ranks(today)["黄金"]))
        self.new_ledger()                                                                    # 对照：不标断档时黄金占第 1、半导体被挤到第 2
        self.replay(panel.assign(data_hole=0), bench, days=DAYS[: DAYS.index(d) + 1])
        self.assertEqual(self.L.card("T-2026-001")["crowd_rs_1m_rank"], 2)

    def test_lifecycle_matches_the_engine(self):
        panel, bench = make_panel()
        self.replay(panel, bench)
        x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
        self.assertEqual(self.engine_exit(panel), (x["exit_date"], x["exit_price"], x["exit_reason"]))

    def test_manual_and_thesis_void_signals_take_the_same_path(self):
        """owner 在某日收盘后声明手动 / 论点作废 → 写出场信号（该日为信号行）→ 每日任务在次日开盘成交；论点作废一律证伪。"""
        for reason, manual, want in (("手动", "流动性不足", "部分"), ("论点作废", None, "证伪")):
            with self.subTest(reason):
                self.new_ledger()
                panel, bench = make_panel()
                job = DailyJob(self.L, panel, bench, rules=RULES, instruments=INST)
                decide = DAYS[DAYS.index(SIGNAL) + 5]                                   # 进场后第 5 天收盘后决定
                for d in DAYS:
                    self.now = f"{d}T16:00"
                    job.run(d)
                    if d == decide:
                        self.now = f"{d}T20:00"
                        close = self.L.daily_rows("T-2026-001")[-1]["close"]
                        self.L.signal_exit("T-2026-001", d, reason, close, manual)
                x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = 'T-2026-001'").fetchone())
                nxt = DAYS[DAYS.index(decide) + 1]
                self.assertEqual((x["exit_date"], x["exit_reason"], x["manual_reason"], x["exit_price"]),
                                 (nxt, reason, manual, float(panel[(panel["container"] == "半导体") & (panel["date"] == nxt)]["open"].iloc[0])))
                f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = 'T-2026-001'").fetchone())
                self.assertEqual(f["final_score"], want)

    def test_rerun_is_idempotent(self):
        panel, bench = make_panel()
        self.replay(panel, bench)
        before = dump(self.L)
        again = self.replay(panel, bench)
        self.assertFalse(any(r.changed() for r in again))
        self.assertEqual(dump(self.L), before)

    def test_no_lookahead(self):
        panel, bench = make_panel()
        self.replay(panel, bench)
        full = dump(self.L)
        self.assertEqual(len(full["ew_daily"]), len(DAYS))
        self.new_ledger()
        self.replay(panel, bench, truncate=True)
        self.assertEqual(dump(self.L), full)                             # 含 ew_daily：等权日收益逐日追加，与一次给全数据相同

    def test_voids_count_in_denominator(self):
        # 黄金 02-27 月末 z ≤ −2，次日开盘远低于失效位 → 未进场而失效
        panel, bench = make_panel({("黄金", "2026-02-27"): -3.0})
        nxt = pd.Timestamp("2026-03-02")
        panel.loc[(panel["container"] == "黄金") & (panel["date"] == nxt), ["open", "low"]] = [200.0, 199.0]
        reps = {r.day: r for r in self.replay(panel, bench)}
        self.assertEqual(reps["2026-03-02"].voids, [("T-2026-002", "开盘已在失效位下方")])
        s = self.L.summary()
        self.assertEqual((s["denominator"], s["by_status"].get("作废")), (2, 1))

    def test_positions_full(self):
        panel, bench = make_panel({("黄金", SIGNAL): -2.2})
        reps = {r.day: r for r in self.replay(panel, bench, days=DAYS[:30], p=Params(max_positions=1))}
        self.assertEqual(reps["2026-02-02"].entries, ["T-2026-001"])          # 半导体 z 更低，先进
        self.assertEqual(reps["2026-02-02"].voids, [("T-2026-002", "持仓已满")])

    def test_rebuilding_indicators_from_raw_each_day_matches(self):
        """每天只用 ≤ D 的原始行情、以 D 为 end 现算指标（= daily 的实跑路径），结果与预先算好的面板逐表相同。"""
        panel, bench = make_panel()
        self.replay(panel, bench)
        full = dump(self.L)
        self.new_ledger()
        raw = {n: g.drop(columns=["state", "rs_1m", "atr20", "z_month"]).assign(volume=1000.0).reset_index(drop=True)
               for n, g in panel.groupby("container")}
        for d in DAYS:
            self.now = f"{d}T16:00"
            cut = pd.Timestamp(d)
            b = bench[bench.index <= cut]
            frames = []
            for n, g in raw.items():
                q = container_panel(g[g["date"] <= cut].reset_index(drop=True), b, cut.date(), compute_indicators=True)
                q.insert(1, "container", n)
                frames.append(q)
            live = pd.concat(frames, ignore_index=True)
            # 构造面板的指标是手填的：把现算的 z_month / atr20 换成同一组手填值，只验「现算路径 + 每日截断」不丢月末信号
            live = live.drop(columns=["z_month", "atr20", "state", "rs_1m"]).merge(
                panel[panel["date"] <= cut][["date", "container", "z_month", "atr20", "state", "rs_1m"]], on=["date", "container"])
            from src.indicators.metrics import month_end_flags
            me = live.groupby("container", group_keys=False).apply(lambda g: month_end_flags(g["date"], cut.date()))
            live.loc[~me.reindex(live.index).fillna(False).astype(bool), "z_month"] = np.nan
            DailyJob(self.L, live, b, rules=RULES, instruments=INST).run(d)
        self.assertEqual(dump(self.L), full)

    def test_cash_and_risk_limits(self):
        # 四个低波容器同日恐慌：每个按风险算都顶到 25%，现金只够 4 个；第 5 个作废
        panel, bench = make_panel()
        extra = []
        for k in range(5):
            g = panel[panel["container"] == "黄金"].copy()
            g["container"], g["atr20"] = f"低波{k}", 0.2
            g.loc[g["date"] == pd.Timestamp(SIGNAL), "z_month"] = -2.1 - 0.1 * k
            extra.append(g)
        panel = pd.concat([panel] + extra, ignore_index=True)
        inst = {**INST, **{f"低波{k}": {"code": f"51000{k}", "name": f"低波{k}"} for k in range(5)}}
        job = DailyJob(self.L, panel, bench, rules=RULES, instruments=inst)
        reps = {}
        for d in DAYS[: DAYS.index(SIGNAL) + 2]:
            self.now = f"{d}T16:00"
            reps[d] = job.run(d)
        day = DAYS[DAYS.index(SIGNAL) + 1]
        sizes = [r[0] for r in self.L.conn.execute("SELECT size_pct FROM entries")]
        self.assertLessEqual(sum(sizes), 100 + 1e-9)
        self.assertIn("现金或风险额度不足", [w for _, w in reps[day].voids])

    def test_catch_up_run_does_not_create_late_cards(self):
        panel, bench = make_panel()
        job = DailyJob(self.L, panel, bench, rules=RULES, instruments=INST)
        self.now = "2026-02-03T16:00"                                    # 01-30 的信号拖到 02-03 才补跑
        rep = job.run(SIGNAL)
        self.assertEqual(rep.created, [])
        self.assertIn("立卡时限", rep.skipped[0])

    def test_event_card(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        (d / "2026-03-10.json").write_text(json.dumps([{
            "container": "黄金", "thesis": "央行连续增持，一手数据确认", "evidence_status": "有证据",
            "evidence": [{"source_id": "ENE-EIA-WPSR", "published_at": "2026-03-09T22:30", "summary": "（构造）", "url": "https://www.eia.gov/",
                          "first_seen_at": "2026-03-09T22:40", "available_at": "2026-03-09T22:30",
                          "snapshot_path": "snapshots/x.pdf", "snapshot_sha256": "b" * 64}],
            "agent_score": {"score": 3, "reason": "一手数据"}, "expectation": EVENT_EXP,
            "thesis_invalidation": {"source_id": "ENE-EIA-WPSR", "deadline": "2026-04-10", "statement": "4 月 10 日前库存转增即失效"}}],
            ensure_ascii=False), encoding="utf-8")
        panel, bench = make_panel()
        reps = {r.day: r for r in self.replay(panel, bench, days=[x for x in DAYS if x <= "2026-04-13"], events_dir=d)}
        cid = reps["2026-03-10"].created[0]
        c = self.L.card(cid)
        self.assertEqual((c["trigger_type"], c["expectation_benchmark"], c["thesis_inval_source_id"]), ("事件驱动", "沪深300", "ENE-EIA-WPSR"))
        self.assertEqual((c["evidence_status"], c["scoring_rule"], c["expectation_horizon_days"], c["expectation_target_excess_pct"],
                          c["expectation_target_r"]), ("有证据", "schema-v1-§3", 20, 3.0, None))       # 菜单第 1 项，逐卡预期
        self.assertEqual(len(self.L.evidence(cid)), 1)
        self.assertEqual(self.L.conn.execute("SELECT count(*) FROM strength_scores WHERE card_id = ?", (cid,)).fetchone()[0], 1)
        self.assertEqual(reps["2026-03-11"].entries, [cid])
        self.assertTrue(any("论点失效判定日" in x for x in reps["2026-04-10"].reminders))

    def test_event_draft_on_a_hole_day_is_returned(self):
        """v1.1-i 第 4 条：事件草稿的容器当日数据断档（收盘、ATR 都是陈旧拷贝）→ 不立卡，退回并注明；不断档照常立卡。"""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        draft = {"container": "黄金", "thesis": "构造事件", "evidence_status": "已检索无证据", "evidence": [],
                 "agent_score": {"score": 1, "reason": "弱"}, "expectation": EVENT_EXP,
                 "thesis_invalidation": {"source_id": "ENE-EIA-WPSR", "deadline": "2026-06-30", "statement": "构造"}}
        (d / "2026-03-10.json").write_text(json.dumps([draft], ensure_ascii=False), encoding="utf-8")
        panel, bench = make_panel()
        holed = panel.copy()
        holed.loc[(holed["container"] == "黄金") & (holed["date"] == pd.Timestamp("2026-03-10")), "data_hole"] = 1
        rep = {r.day: r for r in self.replay(holed, bench, days=[x for x in DAYS if x <= "2026-03-10"], events_dir=d)}["2026-03-10"]
        self.assertEqual(rep.created, [])
        self.assertTrue(any("数据断档" in x and "未立卡" in x for x in rep.skipped), rep.skipped)
        self.new_ledger()
        rep = {r.day: r for r in self.replay(panel, bench, days=[x for x in DAYS if x <= "2026-03-10"], events_dir=d)}["2026-03-10"]
        self.assertEqual(len(rep.created), 1)

    def test_event_drafts_are_validated_one_by_one(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        good = {"container": "黄金", "thesis": "论点一", "evidence_status": "已检索无证据", "evidence": [],
                "agent_score": {"score": 1, "reason": "弱"}, "expectation": EVENT_EXP,
                "thesis_invalidation": {"source_id": "ENE-EIA-WPSR", "deadline": "2026-04-10", "statement": "到期未兑现即失效"}}
        drafts = [good, {**good, "thesis": "论点二"}, {**good, "thesis": "长" * 81}, {**good, "agent_score": None}, {**good, "container": "不存在"},
                  {**good, "evidence_status": "未检索"}, {**good, "evidence_status": "有证据"},        # 事件卡必须检索过；有证据须带证据
                  {**good, "expectation": {**EVENT_EXP, "horizon_days": None}}, {**good, "expectation": {**EVENT_EXP, "benchmark": "自身"}},
                  # 不替起草人改参数：字符串、小数天数、布尔一律整条退回，也不让整份草稿崩掉
                  {**good, "expectation": {**EVENT_EXP, "horizon_days": "二十"}}, {**good, "expectation": {**EVENT_EXP, "target_excess_pct": "5%"}},
                  {**good, "expectation": {**EVENT_EXP, "horizon_days": 20.7}}, {**good, "expectation": {**EVENT_EXP, "horizon_days": True}},
                  "不是对象", {**good, "thesis": 123}]
        (d / "2026-03-10.json").write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
        panel, bench = make_panel()
        rep = self.replay(panel, bench, days=["2026-03-10"], events_dir=d)[0]
        self.assertEqual(len(rep.created), 2)                               # 同日同容器两条都立卡
        self.assertEqual(len(rep.skipped), 13)
        self.assertTrue(any("超过 80 字" in x for x in rep.skipped))
        self.assertEqual(sum("evidence_status" in x for x in rep.skipped), 2)
        self.assertEqual(sum("逐卡预期" in x for x in rep.skipped), 6)
        self.assertEqual({c: self.L.card(c)["expectation_horizon_days"] for c in rep.created}.popitem()[1], 20)
        self.assertEqual({self.L.card(c)["thesis"] for c in rep.created}, {"论点一", "论点二"})
        self.assertEqual({self.L.card(c)["evidence_status"] for c in rep.created}, {"已检索无证据"})

    def test_benchmark_window_open_to_open(self):
        """v1.1-e：沪深300 基准取进场日开盘到出场日开盘；没有开盘价时退回前一日收盘到前一日收盘。"""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        draft = {"container": "半导体", "thesis": "构造事件", "evidence_status": "已检索无证据", "evidence": [],
                 "agent_score": {"score": 1, "reason": "弱"}, "expectation": EVENT_EXP,
                 "thesis_invalidation": {"source_id": "ENE-EIA-WPSR", "deadline": "2026-06-30", "statement": "构造"}}
        (d / f"{SIGNAL}.json").write_text(json.dumps([draft], ensure_ascii=False), encoding="utf-8")
        panel, bench = make_panel()
        panel.loc[(panel["container"] == "半导体") & (panel["date"] == pd.Timestamp(SIGNAL)), "z_month"] = np.nan    # 只留事件卡
        bench_open = bench * 0.99                                                                  # 构造开盘价 ≠ 收盘价
        results = {}
        for label, kw in (("open", {"bench_open": bench_open}), ("fallback", {})):
            self.new_ledger()
            self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 20], events_dir=d, **kw)
            cid = self.L.cards_in("当下", "过去")[0]
            e = dict(self.L.conn.execute("SELECT * FROM entries WHERE card_id = ?", (cid,)).fetchone())
            x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
            held = x["exit_price"] * (1 - 0.0005) / (e["entry_price"] * (1 + 0.0005)) - 1
            results[label] = (held, e, x)
            if label == "open":                                                                      # 开盘价路径也无未来
                full = dump(self.L)
                self.new_ledger()
                self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 20], events_dir=d, truncate=True, **kw)
                self.assertEqual(dump(self.L), full)
        held, e, x = results["open"]
        b = bench_open[pd.Timestamp(x["exit_date"])] / bench_open[pd.Timestamp(e["entry_date"])] - 1
        self.assertAlmostEqual(x["realized_excess_pct"], (held - b) * 100, places=5)
        held, e, x = results["fallback"]
        prev = lambda s: DAYS[DAYS.index(s) - 1]                                                    # noqa: E731
        b = bench[pd.Timestamp(prev(x["exit_date"]))] / bench[pd.Timestamp(prev(e["entry_date"]))] - 1
        self.assertAlmostEqual(x["realized_excess_pct"], (held - b) * 100, places=5)

    def test_ew_rows_are_append_only(self):
        """等权日收益在台账库内（replan §11）：文件丢失、末尾截断、换成别的面板的文件这几种情况不再可能——存储层拒绝删改与乱序。"""
        panel, bench = make_panel()
        self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 5])
        before = dump(self.L)
        for sql in ("DELETE FROM ew_daily WHERE date = '2026-01-05'", "UPDATE ew_daily SET ew_level = 1.5 WHERE date = '2026-01-30'",
                    "INSERT OR REPLACE INTO ew_daily VALUES ('2026-01-30', 0, 1.5, 3, '2026-02-06T16:00')"):
            with self.subTest(sql), self.assertRaises(sqlite3.DatabaseError):
                self.L.conn.execute(sql)
        last = max(self.L.ew_rows())
        lvl = self.L.ew_rows()[last][1]
        self.now = "2026-03-31T16:00"
        for day, ret, level in (("2025-12-31", 0.0, lvl), ("2026-01-17", 0.0, lvl), (last, 0.0, lvl),          # 补记更早的日子（表里没有的）/ 重复
                                ("2026-03-02", 0.01, lvl * 1.02)):                                              # 点位不连乘
            with self.subTest(day), self.assertRaises(LedgerError):
                self.L.record_ew(day, ret, level, 3)
        self.assertEqual(dump(self.L), before)
        fresh = Ledger(":memory:", clock=lambda: "2026-03-31T16:00", replay=True)
        self.addCleanup(fresh.close)
        for ret, level in ((0.0, 2.0), (0.01, 1.01)):                                   # 第一条点位必须是 1、收益 0
            with self.subTest(level=level), self.assertRaisesRegex(LedgerError, "第一条"):
                fresh.record_ew("2026-01-02", ret, level, 3)
        self.assertEqual(fresh.ew_rows(), {})

    def test_skipped_days_or_tampered_ew_block_the_day(self):
        """漏跑（表的最后一条早于上一交易日）或有人绕过触发器改了卡片当天的点位：台账不动。"""
        panel, bench = make_panel()
        self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 3])
        before = dump(self.L)
        rep = self.replay(panel, bench, days=[DAYS[DAYS.index(SIGNAL) + 6]])[0]
        self.assertIn("漏跑", rep.blocked)
        self.L.conn.execute("DROP TRIGGER ew_daily_no_update")                    # 蓄意篡改（存储层防不了，任务层兜底）
        self.L.conn.execute("UPDATE ew_daily SET ew_level = 1.5 WHERE date = ?", (SIGNAL,))
        rep = self.replay(panel, bench, days=[DAYS[DAYS.index(SIGNAL) + 3]])[0]
        self.assertIn("对不上", rep.blocked)
        self.assertEqual({k: v for k, v in dump(self.L).items() if k != "ew_daily"}, {k: v for k, v in before.items() if k != "ew_daily"})


class Pieces(unittest.TestCase):
    def load(self, cfg: dict) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        self.addCleanup(Path(f.name).unlink)
        self.problems = []
        return R.load_rule_config(Path(f.name), self.problems)

    def test_rule_config_reports_requested_but_refused(self):
        self.load({**CONFIG, "confirmed_terms": None})
        self.assertTrue(self.problems and "confirmed_terms" in self.problems[0])
        self.assertEqual(set(self.load({**CONFIG, "恐慌下轨": {**CONFIG["恐慌下轨"], "target_r": 3}})), {"事件驱动"})
        self.assertTrue(self.problems and "菜单第 2 项" in self.problems[0])                   # 恐慌被拒不静默
        self.load(json.loads((ROOT / "config" / "ledger-rules.json").read_text(encoding="utf-8")))
        self.assertEqual(self.problems, [])                                                    # 全关：没有请求，不算问题

    def test_rule_config_requires_confirmed_terms_and_enabled(self):
        self.assertEqual(R.TERMS_VERSION, "jobs-daily-v5")
        self.assertEqual(self.load(CONFIG), RULES)
        self.assertEqual(self.load({**CONFIG, "confirmed_terms": None}), {})                  # 没确认记账口径：不启用
        for old in ("jobs-daily-v1", "jobs-daily-v2", "jobs-daily-v3", "jobs-daily-v4"):    # 旧口径（v1.1-i 之前）的确认不算数
            self.assertEqual(self.load({**CONFIG, "confirmed_terms": old}), {})
        self.assertEqual(set(self.load({**CONFIG, "事件驱动": {"enabled": False}})), {"恐慌下轨"})
        self.assertEqual(set(self.load({**CONFIG, "恐慌下轨": {**CONFIG["恐慌下轨"], "enabled": "true"}})), {"事件驱动"})

    def test_rule_config_panic_must_be_menu_two(self):
        for bad in ({"target_r": 3}, {"horizon_days": 20}, {"target_excess_pct": 5.0}, {"benchmark": "沪深300"},
                    {"scoring_rule": "schema-v1-§3"}):
            self.assertNotIn("恐慌下轨", self.load({**CONFIG, "恐慌下轨": {**CONFIG["恐慌下轨"], **bad}}), bad)

    def test_shipped_config_is_all_off(self):
        """A7：配置值按 v1.1 写好，但 V1 结论前全部关闭；Cowork 填 confirmed_terms 并打开 enabled 后才启用。"""
        cfg = json.loads((ROOT / "config" / "ledger-rules.json").read_text(encoding="utf-8"))
        self.assertEqual(R.load_rule_config(ROOT / "config" / "ledger-rules.json"), {})
        self.assertEqual((cfg["恐慌下轨"]["enabled"], cfg["事件驱动"]["enabled"]), (False, False))
        on = {**cfg, "confirmed_terms": R.TERMS_VERSION, "恐慌下轨": {**cfg["恐慌下轨"], "enabled": True},
              "事件驱动": {**cfg["事件驱动"], "enabled": True}}
        self.assertEqual(self.load(on), RULES)                                                 # 只差确认与开关

    def test_preflight(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, bench = make_panel()
        cov = [dict(theme_id="T01", container="沪深300", status="retained", series_code="H00300", series_adj="raw", route_used="csi"),
               dict(theme_id="T06", container="半导体", status="retained", series_code="X", series_adj="raw", route_used="csi"),
               dict(theme_id="T35", container="纳指100", status="retained", series_code="NDX", series_adj="raw", route_used="yahoo"),
               dict(theme_id="T15", container="原油", status="flagged", series_code="", series_adj="", error="eia: 403")]
        blocking, notes = preflight(panel, bench, "2026-02-03", cov, set())                     # 首次运行
        self.assertEqual(blocking, [])
        self.assertTrue(notes and "纳指100" in notes[0])                                    # 海外缺行只提示
        blocking, _ = preflight(panel, bench, "2026-02-04", cov, {"2026-02-02"})               # 漏跑 02-03
        self.assertIn("漏跑 2026-02-03", blocking[0])
        late = panel[~((panel["container"] == "半导体") & (panel["date"] == pd.Timestamp("2026-02-03")))]
        blocking, _ = preflight(late, bench, "2026-02-03", cov, {"2026-02-02"})
        self.assertIn("半导体", blocking[0])                                                 # A 股指数缺行 = 数据未到
        blocking, _ = preflight(panel, bench, "2026-02-07", cov, set())                        # 周六
        self.assertIn("不是基准交易日", blocking[0])

    def test_next_weekday_open(self):
        self.assertEqual(next_weekday_open("2026-10-09"), "2026-10-12T09:30")
        self.assertEqual(next_weekday_open("2026-10-12"), "2026-10-13T09:30")
        self.assertEqual(next_weekday_open("2026-09-30"), "2026-10-01T09:30")                 # 没有日历：国庆节也按工作日（偏严）
        cal = pd.DatetimeIndex([d for d in pd.bdate_range("2026-09-01", "2026-10-31") if not ("2026-10-01" <= d.date().isoformat() <= "2026-10-07")])
        self.assertEqual(next_weekday_open("2026-09-30", cal), "2026-10-08T09:30")            # 有日历：下一交易日
        self.assertEqual(next_weekday_open("2026-10-30", cal), "2026-11-02T09:30")            # 日历没覆盖到：退回工作日

    def test_ew_store(self):
        L = Ledger(":memory:", clock=lambda: "2026-03-10T16:00", replay=True)
        self.addCleanup(L.close)
        p = pd.DataFrame({"date": pd.to_datetime(["2026-03-02"] * 2 + ["2026-03-03"] * 3 + ["2026-03-04"] * 3),
                          "container": ["a", "b", "a", "b", "c", "a", "b", "c"],
                          "close": [100.0, 50.0, 110.0, 50.0, 7.0, 110.0, 55.0, 7.7]})
        s = EwStore(L)
        self.assertEqual(s.ensure(p, pd.Timestamp("2026-03-02")), 1.0)                         # 第一天点位 1
        self.assertAlmostEqual(s.ensure(p, pd.Timestamp("2026-03-03")), 1.05)                  # (10% + 0%) / 2；c 新加入当天不计
        self.assertAlmostEqual(s.ensure(p, pd.Timestamp("2026-03-04")), 1.05 * 1.0 + 1.05 * (0 + 0.1 + 0.1) / 3)
        rows = L.ew_rows()
        self.assertEqual((sorted(rows), [rows[d][2] for d in sorted(rows)]), (["2026-03-02", "2026-03-03", "2026-03-04"], [2, 2, 3]))
        again = EwStore(L)                                                                     # 重读库；重跑不追加
        self.assertAlmostEqual(again.ensure(p, pd.Timestamp("2026-03-03")), 1.05)
        self.assertEqual(L.ew_rows(), rows)
        # 容器集合以后变化：旧点位不重算（只追加）
        p2 = p[p["container"] != "b"]
        self.assertAlmostEqual(EwStore(L).ensure(p2, pd.Timestamp("2026-03-03")), 1.05)
        self.assertIsNone(EwStore(L).ensure(p, pd.Timestamp("2026-03-01")))                    # 不补记更早的日子
        self.assertEqual(L.ew_rows(), rows)
        self.assertEqual(L.conn.execute("SELECT recorded_at FROM ew_daily").fetchall()[0][0], "2026-03-10T16:00")   # 数据库时钟

    def test_live_panel_from_db(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, _ = make_panel()
        db = tmp / "market.sqlite"
        con = open_db(db)
        for name, code, route in (("沪深300", "H00300", "csi"), ("半导体", "H30184CNY010", "csi"), ("黄金", "NDX", "yahoo")):
            g = panel[panel["container"] == name]
            if route == "yahoo":
                g = g[g["date"] <= pd.Timestamp("2026-03-13")]              # 海外序列 03-13 之后停更
            put(con, code, g[["date", "open", "high", "low", "close"]].assign(volume=1000.0), route)
        put_coverage(con, [dict(theme_id="T01", container="沪深300", status="retained", series_code="H00300", series_adj="raw", route_used="csi"),
                           dict(theme_id="T06", container="半导体", status="retained", series_code="H30184CNY010", series_adj="raw", route_used="csi"),
                           dict(theme_id="T15", container="原油", status="flagged", error="eia: 403"),
                           dict(theme_id="T35", container="纳指100", status="retained", series_code="NDX", series_adj="raw", route_used="yahoo")])
        con.close()
        sha = __import__("src.data.db", fromlist=["sha256_file"]).sha256_file(db)
        p, b, bo, problems = live_panel(db, date(2026, 3, 31))
        self.assertEqual(__import__("src.data.db", fromlist=["sha256_file"]).sha256_file(db), sha)        # 只读打开
        self.assertEqual(set(p["container"]), {"沪深300", "半导体", "纳指100"})
        self.assertEqual(p["date"].max(), pd.Timestamp("2026-03-31"))
        self.assertTrue(problems and "原油" in problems[0])
        # I-20 之后停更不再表现为缺行（D 日是平盘行），必须由报告点出来
        stale = [x for x in problems if "纳指100" in x]
        self.assertEqual(len(stale), 1)
        self.assertIn("2026-03-13", stale[0])
        self.assertIn("可能停更", stale[0])
        _, _, _, problems = live_panel(db, date(2026, 3, 13))
        self.assertFalse(any("纳指100" in x for x in problems))           # 03-13 用 03-12 的 K 线，不是平盘
        hs = panel[panel["container"] == "沪深300"].set_index("date")
        self.assertTrue(bo.index.equals(b.index))
        self.assertTrue(np.allclose(bo.to_numpy(), hs.loc[b.index, "open"].to_numpy()))           # 基准开盘价取原始值
        cal = pd.DatetimeIndex(pd.bdate_range("2026-01-01", "2026-06-30"))
        import src.jobs.live as live_mod
        with mock.patch.object(live_mod, "container_panel", wraps=live_mod.container_panel) as cp:
            live_panel(db, date(2026, 3, 30), cal)
        self.assertTrue(all(c.args[3] is cal for c in cp.call_args_list))                          # 交易日历传到月末判定
        self.assertEqual(live_mod.instruments(covs=live_mod.coverage(db))["半导体"]["research_code"], "H30184CNY010")

    def test_panel_without_data_hole_is_rejected(self):
        panel, bench = make_panel()
        L = Ledger(":memory:", clock=lambda: "2026-01-02T16:00", replay=True)
        self.addCleanup(L.close)
        with self.assertRaisesRegex(ValueError, "data_hole"):                                 # 不默认 0
            DailyJob(L, panel.drop(columns="data_hole"), bench, rules=RULES, instruments=INST)
        with self.assertRaisesRegex(ValueError, "data_hole"):
            DailyJob(L, panel.assign(data_hole=np.where(panel.index == 3, np.nan, 0)), bench, rules=RULES, instruments=INST)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        write_panel_db(tmp / "p.sqlite", panel.assign(data_hole=0), pd.DataFrame({"date": bench.index, "hs300": bench.values, "hs300_open": bench.values}), {})
        con = sqlite3.connect(tmp / "p.sqlite")
        con.execute("ALTER TABLE panel DROP COLUMN data_hole")                               # 旧面板库：没有 data_hole
        con.commit()
        con.close()
        (tmp / "rules.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "回放库未建"), mock.patch("builtins.print"):
            jobs_main(["replay", "--panel", str(tmp / "p.sqlite"), "--from", "2026-01-02", "--to", "2026-01-30",
                       "--rules", str(tmp / "rules.json"), "--db", str(tmp / "r.sqlite"), "--calendar", str(tmp / "none.sqlite")])
        self.assertFalse((tmp / "r.sqlite").exists())

    def test_daily_cli_on_market_db(self):
        """daily 的接线（P7）：只读行情库现算面板，已处理交易日与等权日收益都记在台账库；漏跑一天即拒绝，台账不动。"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, _ = make_panel()
        market = tmp / "market.sqlite"
        con = open_db(market)
        for name, code, route in (("沪深300", "H00300", "csi"), ("半导体", "H30184CNY010", "csi"), ("黄金", "518880", "eastmoney_etf_hfq")):
            put(con, code, panel[panel["container"] == name][["date", "open", "high", "low", "close"]].assign(volume=1000.0), route)
        put_coverage(con, [dict(theme_id="T01", container="沪深300", status="retained", series_code="H00300", series_adj="raw", route_used="csi"),
                           dict(theme_id="T06", container="半导体", status="retained", series_code="H30184CNY010", series_adj="raw", route_used="csi"),
                           dict(theme_id="T16", container="黄金", status="flagged", series_code="518880", series_adj="hfq",
                                route_used="eastmoney_etf_hfq")])
        con.close()
        sha = __import__("src.data.db", fromlist=["sha256_file"]).sha256_file(market)
        (tmp / "rules.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        base = ["daily", "--no-update", "--market", str(market), "--db", str(tmp / "ledger.sqlite"), "--rules", str(tmp / "rules.json")]
        with mock.patch("builtins.print"):
            for d in ("2026-02-02", "2026-02-03", "2026-02-03"):                              # 同一天重跑无妨
                self.assertEqual(jobs_main(base + ["--date", d]), 0)
            self.assertEqual(jobs_main(base + ["--date", "2026-02-05"]), 3)                    # 漏跑 02-04
        L = Ledger(tmp / "ledger.sqlite")
        self.addCleanup(L.close)
        self.assertEqual(L.processed_days(), {"2026-02-02", "2026-02-03"})
        self.assertEqual(sorted(L.ew_rows()), ["2026-02-02", "2026-02-03"])
        self.assertEqual(__import__("src.data.db", fromlist=["sha256_file"]).sha256_file(market), sha)    # --no-update：行情库没被写
        L.mark_processed("2026-02-03")                                                         # 已记过：不重复
        with self.assertRaises(sqlite3.DatabaseError):
            L.conn.execute("DELETE FROM job_days")
        with self.assertRaises(LedgerError):
            L._tx(lambda: L._insert("job_days", {"day": "2026-02-02"}))
        L.close()
        from src.jobs.daily import DayReport
        with mock.patch("src.jobs.__main__.DailyJob.run", return_value=DayReport("2026-02-04", blocked="构造的阻断")), \
             mock.patch("builtins.print"):
            self.assertEqual(jobs_main(base + ["--date", "2026-02-04"]), 3)                    # 台账流程被阻断：不记为已处理
        L = Ledger(tmp / "ledger.sqlite")
        self.assertEqual(L.processed_days(), {"2026-02-02", "2026-02-03"})
        L.close()
        (tmp / "ledger.sqlite").unlink()
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(base + ["--date", "2026-02-07"]), 3)                    # 周六：运行前检查拦下
        self.assertFalse((tmp / "ledger.sqlite").exists())                                    # 被拦下时不建台账库

    def test_replay_cli(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, bench = make_panel()
        write_panel_db(tmp / "panel.sqlite", panel.assign(data_hole=0),
                       pd.DataFrame({"date": bench.index, "hs300": bench.values, "hs300_open": bench.values - 1}), {"end": "2026-04-30"})
        (tmp / "rules.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        args = ["replay", "--panel", str(tmp / "panel.sqlite"), "--from", "2026-01-02", "--to", "2026-03-31",
                "--rules", str(tmp / "rules.json"), "--db", str(tmp / "replay.sqlite"), "--calendar", str(tmp / "no-such-market.sqlite")]
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(args), 0)
        L = sqlite3.connect(tmp / "replay.sqlite")
        self.assertEqual(L.execute("SELECT value FROM ledger_meta WHERE key = 'clock'").fetchone()[0], "replay")
        self.assertEqual(L.execute("SELECT value FROM ledger_meta WHERE key = 'schema'").fetchone()[0], "v1.1-i")
        self.assertEqual(L.execute("SELECT count(*) FROM cards").fetchone()[0], 1)
        ew = L.execute("SELECT min(date), max(date), (SELECT ew_level FROM ew_daily ORDER BY date LIMIT 1) FROM ew_daily").fetchone()
        self.assertEqual(ew, ("2026-01-02", "2026-03-31", 1.0))                                 # 回放的等权日收益记在回放库里
        self.assertEqual(L.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        L.close()
        self.assertFalse(any(tmp.glob("replay.sqlite-*")))
        # 规则全关（仓库里的配置）：直接退出，不建库
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main([*args[:7], "--rules", str(ROOT / "config" / "ledger-rules.json"), "--db", str(tmp / "b.sqlite")]), 2)
        self.assertFalse((tmp / "b.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
