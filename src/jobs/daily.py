"""收盘后的每日流程骨架（replan §3 P5）。一个交易日 D 依次：

  1. 开盘离场：在场卡若在上一行收盘跌破当时生效的止损，按 D 开盘离场（prereg-v1 §4，与 V1 引擎同一时序）
  2. 开盘进场：上一交易日立的候选卡按 D 开盘成交；开盘不高于失效位、持仓已满、已持有该容器、错过次日开盘 → 作废（A4：留在分母）
  3. 收盘每日行：在场卡与跟踪期内的卡各追加一行（收盘、状态、z、排名、R、MFE / MAE、止损）；止损按 §4 只上不下
  4. 跟踪期满：出场后满 tracking_days 行 → 写期满记录，final_score 由存储层按 v1.1-f 机械核对（先判证伪，再按菜单分档）
  5. 触发候选：只接「恐慌下轨」与「事件驱动」（A7），立卡即锁死

幂等：每一步都先查台账已有的记录，同一天重跑不产生任何新行。所有价格都在卡片的研究序列上（后复权 / 全收益点位）。
只验流程，不产出任何研究结论；记账口径按 schema v1.1-e（docs/jobs-daily.md）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from src.indicators.calendar import next_trading_day
from src.ledger.store import Ledger, LedgerError, mechanical_score
from src.research.prereg_v1.config import Params
from . import rules as R
from .ew import EwStore


@dataclass
class DayReport:
    day: str
    exits: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    voids: list = field(default_factory=list)
    daily_rows: int = 0
    finals: list = field(default_factory=list)
    created: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    reminders: list = field(default_factory=list)
    blocked: str = ""                                    # 非空 = 台账一行未动（CLI 不记为已处理）

    def changed(self) -> bool:
        return bool(self.exits or self.entries or self.voids or self.daily_rows or self.finals or self.created)


def default_scorer(c: R.Candidate) -> dict | None:
    """v1.1-a：机械卡 evidence_status = 未检索，不写 agent 分（为空，不是 0）；检索过的卡必须由起草人给分（A1）。"""
    if c.evidence_status == "未检索":
        return None
    if c.agent_score:
        return c.agent_score
    raise ValueError(f"{c.container} {c.trigger_type}：检索过的候选必须带 agent_score")


def creation_cutoff(d: str) -> str:
    """立卡时限：信号日之后第一个工作日 09:30（与存储层 CHECK 同一口径）。补跑超过时限就不立卡。"""
    x = date.fromisoformat(d) + timedelta(days=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return f"{x.isoformat()}T09:30"


def next_weekday_open(d: str, trading_days=None) -> str:
    """owner 评分截止 = 下一交易日 09:30。有交易日历文件时按日历（v1.1-e）；没有时取下一个工作日：
    遇到节假日只会让截止偏早（更严），不会偏晚。"""
    nxt = next_trading_day(date.fromisoformat(d), trading_days)
    if nxt is None:
        nxt = date.fromisoformat(d) + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    return f"{nxt.isoformat()}T09:30"


def _num(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


class DailyJob:
    def __init__(self, ledger: Ledger, panel: pd.DataFrame, bench: pd.Series, *, rules: dict, instruments: dict,
                 events_dir=None, scorer: Callable[[R.Candidate], dict | None] = default_scorer, p: Params = Params(),
                 ew_path: Path | None = None, bench_open: pd.Series | None = None, trading_days=None):
        self.L, self.p, self.rules, self.instruments, self.events_dir, self.scorer = ledger, p, rules, instruments, events_dir, scorer
        self.panel = panel.assign(date=pd.to_datetime(panel["date"])).sort_values(["date", "container"])
        self.bench = bench.sort_index()
        self.bench_open = bench_open.sort_index() if bench_open is not None else None
        self.trading_days = trading_days
        self.ew_store = EwStore(ew_path)          # 等权日收益持久化（v1.1-e）；正式文件由 CLI 传入，None = 只在内存

    # ------------------------------------------------------------ 取数（一律截到 D）
    def _row(self, container: str, d: pd.Timestamp):
        s = self.panel[(self.panel["container"] == container) & (self.panel["date"] == d)]
        return s.iloc[0] if len(s) else None

    def _prev_date(self, container: str, d: pd.Timestamp):
        s = self.panel[(self.panel["container"] == container) & (self.panel["date"] < d)]["date"]
        return s.max() if len(s) else None

    def _level(self, series: pd.Series, d) -> float | None:
        s = series[series.index <= pd.Timestamp(d)]
        return float(s.iloc[-1]) if len(s) else None

    def _bench_return(self, card: dict, entry_date: str, exit_date: str) -> float:
        """v1.1-e：基准窗口 = 进场日开盘到出场日开盘（与卡片成交时点相同，H00300 有开盘价）；
        没有开盘价（等权组合只有收盘点位）时退回前一日收盘到前一日收盘。"""
        if card["expectation_benchmark"] == "沪深300" and self.bench_open is not None:
            o0, o1 = self.bench_open.get(pd.Timestamp(entry_date)), self.bench_open.get(pd.Timestamp(exit_date))
            if o0 is not None and o1 is not None and np.isfinite(o0) and np.isfinite(o1) and o0 > 0:
                return float(o1 / o0 - 1)
        s = self.ew_store.series() if card["expectation_benchmark"] == "等权组合" else self.bench
        b0 = self._level(s, pd.Timestamp(entry_date) - timedelta(days=1))
        b1 = self._level(s, pd.Timestamp(exit_date) - timedelta(days=1))
        return (b1 / b0 - 1) if b0 and b1 else 0.0

    # ------------------------------------------------------------ 主流程
    def run(self, day: str) -> DayReport:
        D = pd.Timestamp(day)
        rep = DayReport(day)
        today = self.panel[self.panel["date"] == D]
        if today.empty:
            rep.skipped.append("当日无任何容器的数据（非交易日或数据未更新）")
            return rep
        rep.blocked = self._ew_problem(D)
        if rep.blocked:
            return rep
        if self.ew_store.ensure(self.panel[self.panel["date"] <= D], D) is None:
            rep.skipped.append(f"等权日收益文件已记到更晚的日期，{day} 不能补记（只追加）；本日反事实等权点位取最近一条")
        self._exits(D, rep)
        self._entries(D, rep)
        self._daily(D, today, rep)
        self._finals(D, rep)
        self._triggers(D, today, rep)
        self._reminders(D, rep)
        return rep

    def _ew_problem(self, D) -> str:
        """等权文件与台账必须是一对（v1.1-e）：文件丢了、末尾少了几行、或换成了别的面板算的文件，基准收益都会静默偏移，
        而出场记录一旦写入就改不了——发现就不动台账。"""
        rows = self.ew_store.rows
        cards = self.L.conn.execute("SELECT id, close_date, cf_ew_level FROM cards ORDER BY close_date, id").fetchall()
        if cards and not rows:
            return f"等权日收益文件不存在，台账已有卡片（最早 {cards[0]['close_date']}）；台账未动，先恢复该文件"
        for c in cards:
            got = rows.get(c["close_date"])
            if got is None or abs(got[1] - c["cf_ew_level"]) > 1e-12 * max(1.0, abs(c["cf_ew_level"])):
                return (f"等权日收益文件与 {c['id']} 冻结的 cf_ew_level 对不上（{c['close_date']}：文件 "
                        f"{'无此日' if got is None else got[1]}，卡片 {c['cf_ew_level']}）；台账未动，先恢复与台账配对的文件")
        key = D.date().isoformat()
        earlier = self.panel.loc[self.panel["date"] < D, "date"]
        if rows and key not in rows and len(earlier) and max(rows) < earlier.max().date().isoformat():
            return (f"等权日收益文件最后一条是 {max(rows)}，早于上一交易日 {earlier.max().date()}：文件末尾少了行或漏跑；"
                    f"台账未动，先恢复该文件或按顺序补跑")
        return ""

    def _reminders(self, D, rep):
        """A3 的论点失效条件到期：骨架不自动判定（需按指定来源人工核对），只提醒。"""
        for cid in self.L.cards_in("当下"):
            c = self.L.card(cid)
            if c["thesis_inval_deadline"] and c["thesis_inval_deadline"] <= D.date().isoformat():
                rep.reminders.append(f"{cid}：论点失效判定日 {c['thesis_inval_deadline']} 已到，按 {c['thesis_inval_source_id']} "
                                     f"核对「{c['thesis_inval_statement']}」，成立则按「论点作废」出场")

    def _exits(self, D, rep):
        for cid in self.L.cards_in("当下"):
            card, rows = self.L.card(cid), self.L.daily_rows(cid)
            if not rows or rows[-1]["date"] >= D.date().isoformat():
                continue
            stop_eff = rows[-2]["stop_now"] if len(rows) > 1 else card["invalidation_price"]
            last = rows[-1]
            if not last["close"] < stop_eff:
                continue
            r = self._row(card["container"], D)
            if r is None or not np.isfinite(r.open):
                rep.skipped.append(f"{cid}：应离场但 {D.date()} 无开盘价，顺延")
                continue
            entry = self._entry(cid)
            r_unit = entry["entry_price"] - card["invalidation_price"]
            activated = any(x["close"] >= entry["entry_price"] + self.p.activate_at_r * r_unit for x in rows[:-1])
            c = self.p.cost_per_side
            px = float(r.open)
            realized_r = (px * (1 - c) - entry["entry_price"] * (1 + c)) / r_unit
            bench_ret = self._bench_return(card, entry["entry_date"], D.date().isoformat())
            held_ret = px * (1 - c) / (entry["entry_price"] * (1 + c)) - 1           # v1.1-e：卡片持有收益含成本
            excess = (held_ret - bench_ret) * 100
            held = self.panel[(self.panel["container"] == card["container"]) & (self.panel["date"] >= pd.Timestamp(entry["entry_date"]))
                              & (self.panel["date"] < D)]
            self.L.exit(cid, exit_date=D.date().isoformat(), exit_price=px, exit_reason="移动止盈" if activated else "失效位",
                        realized_r=round(realized_r, 6), realized_excess_pct=round(excess, 6), holding_days=int(len(held)),
                        exit_signal_close=last["close"])                  # v1.1-f：触发出场的那根收盘，期满时判证伪
            rep.exits.append(cid)

    def _entry(self, cid):
        return dict(self.L.conn.execute("SELECT * FROM entries WHERE card_id = ?", (cid,)).fetchone())

    def _entries(self, D, rep):
        cands = []
        for cid in self.L.cards_in("候选"):
            card = self.L.card(cid)
            if card["close_date"] >= D.date().isoformat():
                continue
            r0 = self._row(card["container"], pd.Timestamp(card["close_date"]))
            z = r0.z_month if r0 is not None and card["trigger_type"] == "恐慌下轨" else np.nan
            prio = float(z) if np.isfinite(z) else 1e6          # I-07：恐慌按 z 从低到高，事件排后
            cands.append((prio, cid, card))
        for _, cid, card in sorted(cands, key=lambda t: (t[0], t[1])):
            prev = self._prev_date(card["container"], D)
            r = self._row(card["container"], D)
            live = [self.L.card(x) | {"entry": self._entry(x)} for x in self.L.cards_in("当下")]
            held = {c["container"] for c in live}
            why = None                                   # 判定顺序与 V1 引擎一致：已持有 → 持仓已满 → 无开盘价 → 开盘在失效位下方 → 额度
            if prev is None or card["close_date"] < prev.date().isoformat():
                why = "未在次一交易日开盘成交"
            elif card["container"] in held:
                why = "已持有该容器（不加仓，I-09）"
            elif len(held) >= self.p.max_positions:
                why = "持仓已满"
            elif r is None or not np.isfinite(r.open):
                why = "次一交易日无开盘价"
            elif r.open <= card["invalidation_price"]:
                why = "开盘已在失效位下方"
            if why is None:
                px = float(r.open)
                r_unit = px - card["invalidation_price"]
                w = min(self.p.risk_per_trade * px / r_unit, self.p.max_weight)                       # I-06
                used_risk = sum(c["entry"]["size_pct"] / 100 * (c["entry"]["entry_price"] - c["invalidation_price"])
                                / c["entry"]["entry_price"] for c in live)
                if used_risk + w * r_unit / px > self.p.max_total_risk + 1e-12:                       # §5 总风险 4%
                    w = max(0.0, (self.p.max_total_risk - used_risk) * px / r_unit)
                used = sum(c["entry"]["size_pct"] for c in live) / 100
                w = min(w, max(0.0, 1 - used))                                                          # I-08 近似：不加杠杆
                if w < self.p.min_weight:
                    why = "现金或风险额度不足"
            if why:
                self.L.void(cid, f"未进场而失效：{why}")
                rep.voids.append((cid, why))
                continue
            self.L.enter(cid, D.date().isoformat(), px, round(w * 100, 6))
            rep.entries.append(cid)

    def _daily(self, D, today, rep):
        ranks = today.set_index("container")["rs_1m"].rank(ascending=False, method="min")
        hs = self._level(self.bench, D)
        for cid in self.L.cards_in("当下", "过去"):
            card = self.L.card(cid)
            r = self._row(card["container"], D)
            rows = self.L.daily_rows(cid)
            if r is None or (rows and rows[-1]["date"] >= D.date().isoformat()):
                continue
            entry = self._entry(cid)
            r_unit = entry["entry_price"] - card["invalidation_price"]
            close = float(r.close)
            r_cur = (close - entry["entry_price"]) / r_unit
            exited = self.L.status(cid) == "过去"
            prev_mfe = rows[-1]["mfe"] if rows else None
            prev_mae = rows[-1]["mae"] if rows else None
            if exited:
                mfe, mae, stop_now = prev_mfe, prev_mae, None
            else:
                mfe = max(r_cur, prev_mfe) if prev_mfe is not None else r_cur
                mae = min(r_cur, prev_mae) if prev_mae is not None else r_cur
                stop_eff = rows[-1]["stop_now"] if rows else card["invalidation_price"]
                if close < stop_eff:
                    stop_now = stop_eff                          # 跌破：止损不再更新，次日开盘离场
                else:
                    closes = [x["close"] for x in rows] + [close]
                    activated = max(closes) >= entry["entry_price"] + self.p.activate_at_r * r_unit
                    atr = float(r.atr20) if np.isfinite(r.atr20) else None
                    stop_now = max(stop_eff, max(closes) - self.p.trail_atr * atr) if activated and atr else stop_eff
            rank = ranks.get(card["container"])
            self.L.append_daily(cid, dict(date=D.date().isoformat(), close=close, state=r.state, z=_num(r.z_month),
                                          rs_1m_rank=int(rank) if rank == rank and rank is not None else None,
                                          r_current=round(r_cur, 6), mfe=_num(mfe), mae=_num(mae), stop_now=_num(stop_now),
                                          bench_close=_num(hs)))
            rep.daily_rows += 1

    def _finals(self, D, rep):
        for cid in self.L.cards_in("过去"):
            card = self.L.card(cid)
            x = dict(self.L.conn.execute("SELECT * FROM exits WHERE card_id = ?", (cid,)).fetchone())
            rows = self.L.daily_rows(cid)
            after = [r for r in rows if r["date"] > x["exit_date"]][: card["tracking_days"]]
            if len(after) < card["tracking_days"]:
                continue
            entry = self._entry(cid)
            r_unit = entry["entry_price"] - card["invalidation_price"]
            last = after[-1]
            max_r_after = max((r["close"] - entry["entry_price"]) / r_unit for r in after)
            mfe_at_exit = max((r["mfe"] for r in rows if r["date"] <= x["exit_date"] and r["mfe"] is not None), default=0.0)
            bench_ret = self._bench_return(card, entry["entry_date"], x["exit_date"])
            self.L.finalize(cid, post_exit_return_pct=round((last["close"] / x["exit_price"] - 1) * 100, 6),
                            post_exit_r=round((last["close"] - entry["entry_price"]) / r_unit, 6),
                            final_score=mechanical_score(card, x),

                            missed_r=round(max(0.0, max_r_after - x["realized_r"]), 6),
                            stop_quality=int(max_r_after - x["realized_r"] >= 1),
                            trail_quality=int(x["realized_r"] >= 0.7 * mfe_at_exit) if x["exit_reason"] == "移动止盈" else None,
                            benchmark_beat=int(bench_ret > 0))
            rep.finals.append(cid)

    def _triggers(self, D, today, rep):
        day = D.date().isoformat()
        if self.L.now() > creation_cutoff(day):
            rep.skipped.append(f"已过 {day} 的立卡时限（{creation_cutoff(day)}）：补跑只处理进出场与每日行，不补立卡")
            return
        cands: list[R.Candidate] = []
        if "恐慌下轨" in self.rules:
            cands += R.panic_candidates(today, self.p.z_threshold)
        if "事件驱动" in self.rules:
            ev, problems = R.event_candidates(today, self.events_dir, day)
            cands += ev
            rep.skipped += problems
        ranks = today.set_index("container")["rs_1m"].rank(ascending=False, method="min")
        for c in sorted(cands, key=lambda c: (c.priority, c.container)):
            key = f"{day}|{c.container}|{c.trigger_type}{c.key_suffix}"
            if self.L.find_by_scan_key(key):
                continue
            inst = self.instruments.get(c.container)
            if not inst:
                rep.skipped.append(f"{c.container}：universe 里没有执行标的，未立卡")
                continue
            exp = c.expectation if c.trigger_type == "事件驱动" else self.rules[c.trigger_type]
            stop = c.close - self.p.stop_atr * c.atr20
            r_unit = c.close - stop
            rank = ranks.get(c.container)
            card = dict(created_at=self.L.now(), close_date=day, scan_key=key, container=c.container,
                        instrument_code=inst["code"], instrument_name=inst["name"], research_index_code=inst.get("research_code"),
                        trigger_type=c.trigger_type, state_at_entry=c.state, thesis=c.thesis, evidence_status=c.evidence_status,
                        scoring_rule=exp["scoring_rule"], expectation_horizon_days=exp["horizon_days"],
                        expectation_target_excess_pct=exp["target_excess_pct"], expectation_target_r=exp["target_r"],
                        expectation_benchmark=exp["benchmark"], invalidation_price=round(stop, 6),
                        invalidation_atr_value=round(c.atr20, 6), invalidation_atr_multiple=self.p.stop_atr,
                        r_unit_per_share=round(r_unit, 6), r_unit_pct_of_nav=self.p.risk_per_trade * 100,
                        planned_size_pct=round(min(self.p.risk_per_trade * c.close / r_unit, self.p.max_weight) * 100, 6),
                        cf_ew_level=self._level(self.ew_store.series(), D), cf_hs300_level=self._level(self.bench, D),
                        cf_container_price=c.close,
                        crowd_rs_1m_rank=int(rank) if rank == rank and rank is not None else None,
                        owner_score_deadline=next_weekday_open(day, self.trading_days))
            if c.trigger_type == "事件驱动" and c.thesis_invalidation:
                ti = c.thesis_invalidation
                card.update(thesis_inval_source_id=ti.get("source_id"), thesis_inval_deadline=ti.get("deadline"),
                            thesis_inval_statement=ti.get("statement"))
            try:
                score = self.scorer(c)
                if score is not None:
                    score = {**score, "scored_at": score.get("scored_at") or self.L.now()}
                cid = self.L.create_card(card, c.evidence, score)
            except (LedgerError, ValueError, KeyError, TypeError, AttributeError) as e:   # 一张卡被拒不挡住其余候选；原因进报告
                rep.skipped.append(f"{c.container} {c.trigger_type}：立卡被拒（{str(e)[:120]}）")
                continue
            rep.created.append(cid)
