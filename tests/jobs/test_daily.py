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

from src.data import runner as data_runner, store                # noqa: E402
from src.jobs import rules as R                                  # noqa: E402
from src.jobs.__main__ import main as jobs_main                  # noqa: E402
from src.jobs.daily import DailyJob, next_weekday_open           # noqa: E402
from src.jobs.ew import EwStore                                  # noqa: E402
from src.jobs.guard import preflight                             # noqa: E402
from src.jobs.live import live_panel                             # noqa: E402
from src.indicators.build import container_panel                 # noqa: E402
from src.ledger.store import Ledger                              # noqa: E402
from src.research.prereg_v1.config import Params                 # noqa: E402

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


def make_panel(extra: dict | None = None) -> tuple[pd.DataFrame, pd.Series]:
    rows = []
    series = {"半导体": semis_path(), "黄金": [300 + 0.2 * k for k in range(len(DAYS))], "沪深300": [4000 + k for k in range(len(DAYS))]}
    for name, closes in series.items():
        for k, d in enumerate(DAYS):
            cl = closes[k]
            op = closes[k - 1] if k else cl
            if name == "半导体" and d == DAYS[DAYS.index(SIGNAL) + 1]:
                op = 100.5
            rows.append(dict(date=pd.Timestamp(d), container=name, open=op, high=max(op, cl) + 0.5, low=min(op, cl) - 0.5,
                             close=cl, state="NEUTRAL", rs_1m=0.01 * (k % 7) - (0.02 if name == "黄金" else 0), atr20=2.0,
                             z_month=np.nan))
    p = pd.DataFrame(rows)
    p.loc[(p["container"] == "半导体") & (p["date"] == pd.Timestamp(SIGNAL)), "z_month"] = -2.5
    for (name, d), z in (extra or {}).items():
        p.loc[(p["container"] == name) & (p["date"] == pd.Timestamp(d)), "z_month"] = z
    bench = p[p["container"] == "沪深300"].set_index("date")["close"]
    return p, bench


def dump(L: Ledger) -> dict:
    tables = ("cards", "evidence", "strength_scores", "entries", "daily", "exits", "finals", "voids")
    return {t: [tuple(r) for r in L.conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in tables}


class Replay(unittest.TestCase):
    def setUp(self):
        self.now = ""
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.new_ledger()

    def new_ledger(self):
        """台账库与等权日收益文件成对新建（正式运行里两者也是一对）。"""
        if getattr(self, "L", None):
            self.L.close()
        self.L = Ledger(":memory:", clock=lambda: self.now, replay=True)
        self.ew = self.tmp / f"ew-{len(list(self.tmp.iterdir()))}.csv"
        self.addCleanup(self.L.close)

    def replay(self, panel, bench, days=DAYS, truncate=False, p=Params(), events_dir=None, **kw):
        reps = []
        job = None if truncate else DailyJob(self.L, panel, bench, rules=RULES, instruments=INST, p=p, events_dir=events_dir,
                                             ew_path=self.ew, **kw)
        for d in days:
            self.now = f"{d}T16:00"
            if truncate:                     # 每天只给当天及以前的数据（沪深300 开盘价也截断）
                cut = pd.Timestamp(d)
                kw_cut = {**kw, **({"bench_open": kw["bench_open"][kw["bench_open"].index <= cut]} if "bench_open" in kw else {})}
                job = DailyJob(self.L, panel[panel["date"] <= cut], bench[bench.index <= cut], rules=RULES, instruments=INST, p=p,
                               events_dir=events_dir, ew_path=self.ew, **kw_cut)
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
        self.assertAlmostEqual(x["realized_r"], (103.5 * (1 - 0.0005) - 100.5 * (1 + 0.0005)) / 4.5, places=6)
        rows = self.L.daily_rows(cid)
        stops = [r["stop_now"] for r in rows if r["stop_now"] is not None]
        self.assertEqual(stops, sorted(stops))                          # 止损只上不下
        self.assertAlmostEqual(max(stops), 104.0)
        # v1.1-e：超额 = 含成本的持有收益 − 等权基准同窗口（等权没有开盘点位 → 前一日收盘到前一日收盘）
        ew = EwStore(self.ew).series()
        self.assertAlmostEqual(card["cf_ew_level"], ew[pd.Timestamp(SIGNAL)])
        prev_exit = DAYS[DAYS.index(x["exit_date"]) - 1]
        held = 103.5 * (1 - 0.0005) / (100.5 * (1 + 0.0005)) - 1
        self.assertAlmostEqual(x["realized_excess_pct"], (held - (ew[pd.Timestamp(prev_exit)] / ew[pd.Timestamp(SIGNAL)] - 1)) * 100,
                               places=5)
        f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual(self.L.status(cid), "已结")
        self.assertEqual(f["final_score"], "部分")                      # 0 < realized_r ≈ 0.64 < 2（菜单第 2 项）
        self.assertEqual(self.L.summary()["denominator"], 1)

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
        full, ew_full = dump(self.L), self.ew.read_text()
        self.new_ledger()
        self.replay(panel, bench, truncate=True)
        self.assertEqual(dump(self.L), full)
        self.assertEqual(self.ew.read_text(), ew_full)                   # 等权文件逐日追加，与一次给全数据相同

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
                q = container_panel(g[g["date"] <= cut].reset_index(drop=True), b, cut.date())
                q.insert(1, "container", n)
                frames.append(q)
            live = pd.concat(frames, ignore_index=True)
            # 构造面板的指标是手填的：把现算的 z_month / atr20 换成同一组手填值，只验「现算路径 + 每日截断」不丢月末信号
            live = live.drop(columns=["z_month", "atr20", "state", "rs_1m"]).merge(
                panel[panel["date"] <= cut][["date", "container", "z_month", "atr20", "state", "rs_1m"]], on=["date", "container"])
            from src.indicators.metrics import month_end_flags
            me = live.groupby("container", group_keys=False).apply(lambda g: month_end_flags(g["date"], cut.date()))
            live.loc[~me.reindex(live.index).fillna(False).astype(bool), "z_month"] = np.nan
            DailyJob(self.L, live, b, rules=RULES, instruments=INST, ew_path=self.ew).run(d)
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
                full, ew_full = dump(self.L), self.ew.read_text()
                self.new_ledger()
                self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 20], events_dir=d, truncate=True, **kw)
                self.assertEqual(dump(self.L), full)
                self.assertEqual(self.ew.read_text(), ew_full)
        held, e, x = results["open"]
        b = bench_open[pd.Timestamp(x["exit_date"])] / bench_open[pd.Timestamp(e["entry_date"])] - 1
        self.assertAlmostEqual(x["realized_excess_pct"], (held - b) * 100, places=5)
        held, e, x = results["fallback"]
        prev = lambda s: DAYS[DAYS.index(s) - 1]                                                    # noqa: E731
        b = bench[pd.Timestamp(prev(x["exit_date"]))] / bench[pd.Timestamp(prev(e["entry_date"]))] - 1
        self.assertAlmostEqual(x["realized_excess_pct"], (held - b) * 100, places=5)

    def test_missing_ew_file_blocks_the_day(self):
        panel, bench = make_panel()
        self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 3])
        before = dump(self.L)
        self.ew.unlink()                                                   # 等权文件丢了：基准会凭空变 0
        rep = self.replay(panel, bench, days=[DAYS[DAYS.index(SIGNAL) + 3]])[0]
        self.assertIn("等权日收益文件不存在", rep.blocked)
        self.assertEqual(dump(self.L), before)
        self.assertFalse(self.ew.exists())

    def test_truncated_or_foreign_ew_file_blocks_the_day(self):
        panel, bench = make_panel()
        self.replay(panel, bench, days=DAYS[: DAYS.index(SIGNAL) + 5])
        before, text = dump(self.L), self.ew.read_text()
        lines = text.splitlines(keepends=True)
        self.ew.write_text("".join(lines[:-3]))                           # 从旧备份恢复：末尾少了 3 天
        rep = self.replay(panel, bench, days=[DAYS[DAYS.index(SIGNAL) + 5]])[0]
        self.assertIn("早于上一交易日", rep.blocked)
        foreign = [x if not x.startswith(SIGNAL) else ",".join(x.split(",")[:2] + ["1.5"] + x.split(",")[3:]) for x in lines]
        self.ew.write_text("".join(foreign))                              # 别的面板算的：信号日点位与卡片冻结值不同
        rep = self.replay(panel, bench, days=[DAYS[DAYS.index(SIGNAL) + 5]])[0]
        self.assertIn("对不上", rep.blocked)
        self.assertEqual(dump(self.L), before)


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
        self.assertEqual(R.TERMS_VERSION, "jobs-daily-v1")
        self.assertEqual(self.load(CONFIG), RULES)
        self.assertEqual(self.load({**CONFIG, "confirmed_terms": None}), {})                  # 没确认记账口径：不启用
        self.assertEqual(self.load({**CONFIG, "confirmed_terms": "jobs-daily-v0"}), {})       # 旧口径的确认不算数
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
        cov = [dict(theme_id="T01", container="沪深300", status="retained", series_file="H00300.csv", route_used="csi"),
               dict(theme_id="T06", container="半导体", status="retained", series_file="x.csv", route_used="csi"),
               dict(theme_id="T35", container="纳指100", status="retained", series_file="NDX.csv", route_used="yahoo")]
        data_runner.write_coverage(tmp / "cov.csv", cov, ["T01", "T06", "T35"])
        blocking, notes = preflight(panel, bench, "2026-02-03", tmp / "cov.csv", set())          # 首次运行
        self.assertEqual(blocking, [])
        self.assertTrue(notes and "纳指100" in notes[0])                                    # 海外缺行只提示
        blocking, _ = preflight(panel, bench, "2026-02-04", tmp / "cov.csv", {"2026-02-02"})   # 漏跑 02-03
        self.assertIn("漏跑 2026-02-03", blocking[0])
        late = panel[~((panel["container"] == "半导体") & (panel["date"] == pd.Timestamp("2026-02-03")))]
        blocking, _ = preflight(late, bench, "2026-02-03", tmp / "cov.csv", {"2026-02-02"})
        self.assertIn("半导体", blocking[0])                                                 # A 股指数缺行 = 数据未到
        blocking, _ = preflight(panel, bench, "2026-02-07", tmp / "cov.csv", set())            # 周六
        self.assertIn("不是基准交易日", blocking[0])

    def test_next_weekday_open(self):
        self.assertEqual(next_weekday_open("2026-10-09"), "2026-10-12T09:30")
        self.assertEqual(next_weekday_open("2026-10-12"), "2026-10-13T09:30")
        self.assertEqual(next_weekday_open("2026-09-30"), "2026-10-01T09:30")                 # 没有日历：国庆节也按工作日（偏严）
        cal = pd.DatetimeIndex([d for d in pd.bdate_range("2026-09-01", "2026-10-31") if not ("2026-10-01" <= d.date().isoformat() <= "2026-10-07")])
        self.assertEqual(next_weekday_open("2026-09-30", cal), "2026-10-08T09:30")            # 有日历：下一交易日
        self.assertEqual(next_weekday_open("2026-10-30", cal), "2026-11-02T09:30")            # 日历没覆盖到：退回工作日

    def test_ew_store(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        p = pd.DataFrame({"date": pd.to_datetime(["2026-03-02"] * 2 + ["2026-03-03"] * 3 + ["2026-03-04"] * 3),
                          "container": ["a", "b", "a", "b", "c", "a", "b", "c"],
                          "close": [100.0, 50.0, 110.0, 50.0, 7.0, 110.0, 55.0, 7.7]})
        s = EwStore(tmp / "ew.csv")
        self.assertEqual(s.ensure(p, pd.Timestamp("2026-03-02")), 1.0)                         # 第一天点位 1
        self.assertAlmostEqual(s.ensure(p, pd.Timestamp("2026-03-03")), 1.05)                  # (10% + 0%) / 2；c 新加入当天不计
        self.assertAlmostEqual(s.ensure(p, pd.Timestamp("2026-03-04")), 1.05 * 1.0 + 1.05 * (0 + 0.1 + 0.1) / 3)
        text = (tmp / "ew.csv").read_text()
        again = EwStore(tmp / "ew.csv")                                                        # 重读文件；重跑不追加
        self.assertAlmostEqual(again.ensure(p, pd.Timestamp("2026-03-03")), 1.05)
        self.assertEqual((tmp / "ew.csv").read_text(), text)
        self.assertEqual(text.splitlines()[0], "date,ew_return,ew_level,n_containers")
        # 容器集合以后变化：旧点位不重算（只追加）
        p2 = p[p["container"] != "b"]
        self.assertAlmostEqual(EwStore(tmp / "ew.csv").ensure(p2, pd.Timestamp("2026-03-03")), 1.05)
        self.assertIsNone(EwStore(tmp / "ew.csv").ensure(p, pd.Timestamp("2026-03-01")))       # 不补记更早的日子
        self.assertEqual((tmp / "ew.csv").read_text(), text)
        mem = EwStore(None)
        mem.ensure(p, pd.Timestamp("2026-03-02"))
        self.assertEqual(len(list(tmp.iterdir())), 1)                                          # 内存模式不写文件

    def test_live_panel_from_raw(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, _ = make_panel()
        for name, fname, route in (("沪深300", "H00300.csv", "csi"), ("半导体", "H30184CNY010.csv", "csi"), ("黄金", "NDX.csv", "yahoo")):
            g = panel[panel["container"] == name]
            if route == "yahoo":
                g = g[g["date"] <= pd.Timestamp("2026-03-13")]              # 海外序列 03-13 之后停更
            store.write(tmp / "raw" / fname, [dict(date=d.date().isoformat(), open=o, high=h, low=l, close=c, volume=1000.0, source=route)
                                               for d, o, h, l, c in zip(g["date"], g["open"], g["high"], g["low"], g["close"])])
        cov = [dict(theme_id="T01", container="沪深300", status="retained", series_file="H00300.csv", route_used="csi"),
               dict(theme_id="T06", container="半导体", status="retained", series_file="H30184CNY010.csv", route_used="csi"),
               dict(theme_id="T15", container="原油", status="flagged", error="eia: 403"),
               dict(theme_id="T35", container="纳指100", status="retained", series_file="NDX.csv", route_used="yahoo")]
        data_runner.write_coverage(tmp / "coverage.csv", cov, ["T01", "T06", "T15", "T35"])
        p, b, bo, problems = live_panel(tmp / "raw", tmp / "coverage.csv", date(2026, 3, 31))
        self.assertEqual(set(p["container"]), {"沪深300", "半导体", "纳指100"})
        self.assertEqual(p["date"].max(), pd.Timestamp("2026-03-31"))
        self.assertTrue(problems and "原油" in problems[0])
        # I-20 之后停更不再表现为缺行（D 日是平盘行），必须由报告点出来
        stale = [x for x in problems if "纳指100" in x]
        self.assertEqual(len(stale), 1)
        self.assertIn("2026-03-13", stale[0])
        self.assertIn("可能停更", stale[0])
        _, _, _, problems = live_panel(tmp / "raw", tmp / "coverage.csv", date(2026, 3, 13))
        self.assertFalse(any("纳指100" in x for x in problems))           # 03-13 用 03-12 的 K 线，不是平盘
        hs = panel[panel["container"] == "沪深300"].set_index("date")
        self.assertTrue(bo.index.equals(b.index))
        self.assertTrue(np.allclose(bo.to_numpy(), hs.loc[b.index, "open"].to_numpy()))           # 基准开盘价取原始值
        cal = pd.DatetimeIndex(pd.bdate_range("2026-01-01", "2026-06-30"))
        import src.jobs.live as live_mod
        with mock.patch.object(live_mod, "container_panel", wraps=live_mod.container_panel) as cp:
            live_panel(tmp / "raw", tmp / "coverage.csv", date(2026, 3, 30), cal)
        self.assertTrue(all(c.args[3] is cal for c in cp.call_args_list))                          # 交易日历传到月末判定

    def test_replay_cli(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, bench = make_panel()
        panel.to_csv(tmp / "panel.csv", index=False, date_format="%Y-%m-%d")
        pd.DataFrame({"date": bench.index, "hs300": bench.values, "hs300_open": bench.values - 1}).to_csv(
            tmp / "bench.csv", index=False, date_format="%Y-%m-%d")
        (tmp / "rules.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        args = ["replay", "--panel", str(tmp / "panel.csv"), "--bench", str(tmp / "bench.csv"), "--from", "2026-01-02",
                "--to", "2026-03-31", "--rules", str(tmp / "rules.json"), "--db", str(tmp / "replay.sqlite"),
                "--calendar", str(tmp / "no-such-calendar.csv")]
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(args), 0)
        L = sqlite3.connect(tmp / "replay.sqlite")
        self.assertEqual(L.execute("SELECT value FROM ledger_meta WHERE key = 'clock'").fetchone()[0], "replay")
        self.assertEqual(L.execute("SELECT value FROM ledger_meta WHERE key = 'schema'").fetchone()[0], "v1.1")
        self.assertEqual(L.execute("SELECT count(*) FROM cards").fetchone()[0], 1)
        L.close()
        ew = pd.read_csv(tmp / "replay.ew_daily.csv")                                           # 回放的等权文件跟着回放库
        self.assertEqual((ew["date"].iloc[0], ew["date"].iloc[-1], ew["ew_level"].iloc[0]), ("2026-01-02", "2026-03-31", 1.0))
        (tmp / "replay.sqlite").unlink()                                                        # 删了库、留着旧等权文件：拒绝
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(args), 3)
        self.assertFalse((tmp / "replay.sqlite").exists())
        # 规则全关（仓库里的配置）：直接退出，不建库
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main([*args[:9], "--rules", str(ROOT / "config" / "ledger-rules.json"), "--db", str(tmp / "b.sqlite")]), 2)
        self.assertFalse((tmp / "b.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
