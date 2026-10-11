"""从 data/market.sqlite 现算面板（每日任务用；研究数据包之外的实时版本，不做数据包复验）。只读打开库。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.data import db as DB, quality
from src.data import universe as U
from src.indicators.build import BENCH_CODE, BuildError, bench_open, container_panel, read_bars, research_frame
from src.indicators.calendar import load_trading_days


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
    只认库内官方交易日历，并执行与正式 build 相同的全池研究输入预检。
    trading_days 仅兼容现有调用方；若传入，必须与同一只读快照中的官方日历完全一致。"""
    try:
        con = DB.connect(db, readonly=True)
    except DB.DbError as e:
        raise SystemExit(f"行情库不可用，不跑每日任务：{e}")
    try:
        con.execute("BEGIN")
        return _live_panel(con, end, trading_days)
    except (BuildError, ValueError) as exc:
        raise SystemExit(f"研究输入不可用，不跑每日任务：{exc}") from exc
    finally:
        con.close()


def _live_panel(con, end: date, trading_days):
    readiness = quality.inspect(con, end)
    if not readiness["research_ready"]:
        issues = readiness["issues"] + [f"{BENCH_CODE}：{x}" for x in readiness["benchmark"]["issues"]]
        issues += [f"{c['container']}（{tid}）：{x}" for tid, c in readiness["containers"].items() for x in c["issues"]]
        raise BuildError("研究输入预检未通过（不补 OHLC、不自动剔除容器）：" + "; ".join(issues))
    official_days = load_trading_days(con)
    if trading_days is not None and not trading_days.equals(official_days):
        raise BuildError("传入交易日历与库内官方 calendar 不一致")
    start = date.fromisoformat(readiness["start"])
    cal = quality.window_days(official_days, start, end)
    # 基准只读取真实收盘，开盘仍为原始值；不用策略修整路径填补。
    bdf = read_bars(con, BENCH_CODE, "raw", end=end)
    bench = bdf.set_index("date")["close"].reindex(cal)
    bopen = bench_open(con).reindex(bench.index)
    frames, problems = [], []
    for c in DB.read_coverage(con):
        if c.get("status") not in U.PANEL_STATUSES:
            continue
        df, rep = research_frame(con, c, cal, strict=True, start=start, end=end)
        if df.empty:
            raise BuildError(f"{c['container']}：对齐 A 股日历后没有行；不自动剔除容器")
        n = rep.get("trailing_stale_days", 0)              # 海外容器 D 日总有一行，没有新 K 线就是平盘：停更不会表现为缺行
        if n:
            problems.append(f"{c['container']}（{c.get('route_used')}）：{end} 沿用 {rep.get('last_bar_date')} 的 K 线，末尾连续平盘 {n} 行"
                            + ("——可能停更或数据未到，先查 update" if n > 3 else "（海外休市）"))
        p = container_panel(df, bench, end, official_days)
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
