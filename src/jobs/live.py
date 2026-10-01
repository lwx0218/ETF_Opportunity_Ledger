"""从 data/market.sqlite 现算面板（每日任务用；研究数据包之外的实时版本，不做数据包复验）。只读打开库。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.data import db as DB
from src.data import universe as U
from src.indicators.build import BENCH_CODE, bench_open, container_panel, load_series, research_frame


def coverage(db: Path = DB.MARKET_DB) -> list[dict]:
    """库里的当前 coverage（每容器最近一次作业那一行）。"""
    con = DB.connect(db, readonly=True)
    try:
        return DB.read_coverage(con)
    finally:
        con.close()


def live_panel(db: Path, end: date, trading_days: pd.DatetimeIndex | None = None
               ) -> tuple[pd.DataFrame, pd.Series, pd.Series, list[str]]:
    """返回 (面板, 沪深300 全收益收盘, 沪深300 全收益开盘, 问题)。开盘价供基准窗口「开盘到开盘」用（v1.1-e）；
    trading_days 是交易日历（库里没有时 None，月末判定退回工作日规则）。"""
    try:
        con = DB.connect(db, readonly=True)
    except DB.DbError as e:
        raise SystemExit(f"行情库不可用，不跑每日任务：{e}")
    try:
        return _live_panel(con, end, trading_days)
    finally:
        con.close()


def _live_panel(con, end: date, trading_days):
    bdf, _ = load_series(con, BENCH_CODE, "raw")
    if bdf.empty:
        raise SystemExit(f"库里没有 {BENCH_CODE}：没有沪深300 全收益基准，不跑每日任务")
    bdf = bdf[bdf["date"] <= pd.Timestamp(end)]
    bench = bdf.set_index("date")["close"]
    bopen = bench_open(con).reindex(bench.index)
    cal = bench.index
    frames, problems = [], []
    for c in DB.read_coverage(con):
        if c.get("status") not in U.PANEL_STATUSES:
            continue
        if not c.get("series_adj") or not con.execute("SELECT 1 FROM bars WHERE code = ? AND adj = ? LIMIT 1",
                                                      (c["series_code"], c["series_adj"])).fetchone():
            problems.append(f"{c['container']}：无研究序列（{(c.get('error') or '')[:60]}）")
            continue
        df, rep = research_frame(con, c, cal)          # 与研究数据包同一口径：I-21 成交量、I-20 A 股日历对齐
        df = df[df["date"] <= pd.Timestamp(end)].reset_index(drop=True)
        if df.empty:
            problems.append(f"{c['container']}：对齐 A 股日历后没有行")
            continue
        n = rep.get("trailing_stale_days", 0)              # 海外容器 D 日总有一行，没有新 K 线就是平盘：停更不会表现为缺行
        if n:
            problems.append(f"{c['container']}（{c.get('route_used')}）：{end} 沿用 {rep.get('last_bar_date')} 的 K 线，末尾连续平盘 {n} 行"
                            + ("——可能停更或数据未到，先查 update" if n > 3 else "（海外休市）"))
        p = container_panel(df, bench, end, trading_days)
        p.insert(1, "container", c["container"])
        frames.append(p)
    if not frames:
        raise SystemExit("没有任何容器有研究序列")
    return pd.concat(frames, ignore_index=True), bench, bopen, problems


def instruments(uni_path: Path = U.UNIVERSE, covs: list[dict] | None = None) -> dict:
    """容器名 → 执行标的与研究序列代码。"""
    cov = {c["theme_id"]: c for c in covs or []}
    out = {}
    for r in U.load(uni_path):
        if r.get("execution_fund_code") and U.in_panel(r):
            out[r["theme"]] = {"code": r["execution_fund_code"], "name": r["execution_fund_name"],
                               "research_code": (cov.get(r["theme_id"]) or {}).get("series_code") or r.get("research_index_code") or None}
    return out
