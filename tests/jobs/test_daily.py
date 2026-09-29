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
from src.jobs.guard import preflight                             # noqa: E402
from src.jobs.live import live_panel                             # noqa: E402
from src.indicators.build import container_panel                 # noqa: E402
from src.ledger.store import Ledger                              # noqa: E402
from src.research.prereg_v1.config import Params                 # noqa: E402

DAYS = [d.date().isoformat() for d in pd.bdate_range("2026-01-02", "2026-04-30")]
SIGNAL = "2026-01-30"                      # 月末
RULES = {"恐慌下轨": {"horizon_days": 20, "target_excess_pct": 5.0, "benchmark": "等权组合"},
         "事件驱动": {"horizon_days": 20, "target_excess_pct": 3.0, "benchmark": "沪深300"}}
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
        self.L = Ledger(":memory:", clock=lambda: self.now, replay=True)
        self.addCleanup(self.L.close)

    def replay(self, panel, bench, days=DAYS, truncate=False, p=Params(), events_dir=None):
        reps = []
        job = None if truncate else DailyJob(self.L, panel, bench, rules=RULES, instruments=INST, p=p, events_dir=events_dir)
        for d in days:
            self.now = f"{d}T16:00"
            if truncate:                     # 每天只给当天及以前的数据
                cut = pd.Timestamp(d)
                job = DailyJob(self.L, panel[panel["date"] <= cut], bench[bench.index <= cut], rules=RULES, instruments=INST, p=p,
                               events_dir=events_dir)
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
        f = dict(self.L.conn.execute("SELECT * FROM finals WHERE card_id = ?", (cid,)).fetchone())
        self.assertEqual(self.L.status(cid), "已结")
        self.assertIn(f["final_score"], ("达标", "部分", "未达"))
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
        full = dump(self.L)
        self.L.close()
        self.L = Ledger(":memory:", clock=lambda: self.now, replay=True)
        self.replay(panel, bench, truncate=True)
        self.assertEqual(dump(self.L), full)

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
        self.L.close()
        self.L = Ledger(":memory:", clock=lambda: self.now, replay=True)
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
            "container": "黄金", "thesis": "央行连续增持，一手数据确认",
            "evidence": [{"source_id": "ENE-EIA-WPSR", "published_at": "2026-03-09T22:30", "summary": "（构造）", "url": "https://www.eia.gov/",
                          "first_seen_at": "2026-03-09T22:40", "available_at": "2026-03-09T22:30",
                          "snapshot_path": "snapshots/x.pdf", "snapshot_sha256": "b" * 64}],
            "agent_score": {"score": 3, "reason": "一手数据"},
            "thesis_invalidation": {"source_id": "ENE-EIA-WPSR", "deadline": "2026-04-10", "statement": "4 月 10 日前库存转增即失效"}}],
            ensure_ascii=False), encoding="utf-8")
        panel, bench = make_panel()
        reps = {r.day: r for r in self.replay(panel, bench, days=[x for x in DAYS if x <= "2026-04-13"], events_dir=d)}
        cid = reps["2026-03-10"].created[0]
        c = self.L.card(cid)
        self.assertEqual((c["trigger_type"], c["expectation_benchmark"], c["thesis_inval_source_id"]), ("事件驱动", "沪深300", "ENE-EIA-WPSR"))
        self.assertEqual(len(self.L.evidence(cid)), 1)
        self.assertEqual(reps["2026-03-11"].entries, [cid])
        self.assertTrue(any("论点失效判定日" in x for x in reps["2026-04-10"].reminders))

    def test_event_drafts_are_validated_one_by_one(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        good = {"container": "黄金", "thesis": "论点一", "evidence": [], "agent_score": {"score": 1, "reason": "弱"},
                "thesis_invalidation": {"source_id": "ENE-EIA-WPSR", "deadline": "2026-04-10", "statement": "到期未兑现即失效"}}
        drafts = [good, {**good, "thesis": "论点二"}, {**good, "thesis": "长" * 81}, {**good, "agent_score": None}, {**good, "container": "不存在"}]
        (d / "2026-03-10.json").write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
        panel, bench = make_panel()
        rep = self.replay(panel, bench, days=["2026-03-10"], events_dir=d)[0]
        self.assertEqual(len(rep.created), 2)                               # 同日同容器两条都立卡
        self.assertEqual(len(rep.skipped), 3)
        self.assertTrue(any("超过 80 字" in x for x in rep.skipped))
        self.assertEqual({self.L.card(c)["thesis"] for c in rep.created}, {"论点一", "论点二"})


class Pieces(unittest.TestCase):
    def test_rule_config_requires_confirmed_terms(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(RULES, f, ensure_ascii=False)
        self.addCleanup(Path(f.name).unlink)
        self.assertEqual(R.load_rule_config(Path(f.name)), {})         # 没确认骨架口径：不启用
        Path(f.name).write_text(json.dumps({"confirmed_terms": R.TERMS_VERSION, **RULES}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(set(R.load_rule_config(Path(f.name))), {"恐慌下轨", "事件驱动"})

    def test_rule_config_requires_all_values(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write((ROOT / "config" / "ledger-rules.example.json").read_text(encoding="utf-8"))
        self.addCleanup(Path(f.name).unlink)
        self.assertEqual(R.load_rule_config(Path(f.name)), {})         # 示例全是 null：一条规则都不启用

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
        p, b, problems = live_panel(tmp / "raw", tmp / "coverage.csv", date(2026, 3, 31))
        self.assertEqual(set(p["container"]), {"沪深300", "半导体", "纳指100"})
        self.assertEqual(p["date"].max(), pd.Timestamp("2026-03-31"))
        self.assertTrue(problems and "原油" in problems[0])
        # I-20 之后停更不再表现为缺行（D 日是平盘行），必须由报告点出来
        stale = [x for x in problems if "纳指100" in x]
        self.assertEqual(len(stale), 1)
        self.assertIn("2026-03-13", stale[0])
        self.assertIn("可能停更", stale[0])
        _, _, problems = live_panel(tmp / "raw", tmp / "coverage.csv", date(2026, 3, 13))
        self.assertFalse(any("纳指100" in x for x in problems))           # 03-13 用 03-12 的 K 线，不是平盘

    def test_replay_cli(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        panel, bench = make_panel()
        panel.to_csv(tmp / "panel.csv", index=False, date_format="%Y-%m-%d")
        pd.DataFrame({"date": bench.index, "hs300": bench.values}).to_csv(tmp / "bench.csv", index=False, date_format="%Y-%m-%d")
        (tmp / "rules.json").write_text(json.dumps({"confirmed_terms": R.TERMS_VERSION, **RULES}, ensure_ascii=False), encoding="utf-8")
        args = ["replay", "--panel", str(tmp / "panel.csv"), "--bench", str(tmp / "bench.csv"), "--from", "2026-01-02",
                "--to", "2026-03-31", "--rules", str(tmp / "rules.json"), "--db", str(tmp / "replay.sqlite")]
        with mock.patch("builtins.print"):
            self.assertEqual(jobs_main(args), 0)
        L = sqlite3.connect(tmp / "replay.sqlite")
        self.assertEqual(L.execute("SELECT value FROM ledger_meta WHERE key = 'clock'").fetchone()[0], "replay")
        self.assertEqual(L.execute("SELECT count(*) FROM cards").fetchone()[0], 1)
        L.close()


if __name__ == "__main__":
    unittest.main()
