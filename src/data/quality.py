"""只读研究输入预检：真实收盘可作基准，策略要求真实 OHLC；不修库、不选样。"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

from . import db as DB
from .universe import PANEL_STATUSES
from src.indicators.calendar import load_trading_days

BENCH_CODE = "H00300"
OVERSEAS_ROUTES = {"yahoo", "stooq", "eia"}


def _positive(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def window_days(trading_days, start: date, end: date):
    """预检与 build 共用的官方交易日窗口；边界由 inspect 验证并报告。"""
    return trading_days[(trading_days.date >= start) & (trading_days.date <= end)]


def input_rows(con, code: str, adj: str, trading_dates: list[str], *, start: date | None,
               end: date, overseas: bool = False) -> tuple[list[dict], list[dict]]:
    """预检与正式 build 共用原行情选择；海外仅保留可被 D−1 消费的原生历史。"""
    lower = start.isoformat() if start else "0001-01-01"
    raw = [dict(r) for r in con.execute(
        "SELECT * FROM bars WHERE code=? AND adj=? AND date>=? AND date<=? ORDER BY date",
        (code, adj, "0001-01-01" if overseas else lower, end.isoformat()))]
    if overseas:
        rows = [r for r in raw if trading_dates and r["date"] < trading_dates[-1]]
    else:
        on_calendar = set(trading_dates)
        rows = [r for r in raw if r["date"] in on_calendar]
    return raw, rows


def inspect(con, end: date, *, start: date | None = None) -> dict:
    """检查调用方的只读快照。官方 calendar 是唯一 A 股日历，缺日不由行情推断。"""
    if start is not None and start > end:
        raise ValueError("start 不能晚于 end")
    requested = {"start": start.isoformat() if start else None, "end": end.isoformat()}
    report = {"requested_window": requested, "trusted_calendar_range": None, "effective_window": None,
              "start": requested["start"], "end": end.isoformat(), "benchmark_ready": False,
              "research_ready": False, "calendar": None, "issues": [], "benchmark": {}, "containers": {}}
    try:
        days = load_trading_days(con)
    except ValueError as exc:
        days = None
        report["issues"].append(f"交易日历不可用：{exc}")
    cal = [] if days is None else [d.date().isoformat() for d in days]
    if not cal:
        report["issues"].append("缺官方交易日历；不得由 H00300 或工作日推造")
    else:
        report["calendar"] = {"days": len(cal), "first": cal[0], "last": cal[-1]}
        report["trusted_calendar_range"] = {"start": cal[0], "end": cal[-1]}
        first = date.fromisoformat(cal[0])
        start = start or first
        if first > start or date.fromisoformat(cal[-1]) < end:
            report["issues"].append("官方交易日历未覆盖请求窗口")
    report["start"] = start.isoformat() if start else None
    window = ([d.date().isoformat() for d in window_days(days, start, end)]
              if days is not None and start is not None else [])
    report["effective_window"] = {"start": report["start"], "end": end.isoformat(),
                                  "first_trading_day": window[0] if window else None,
                                  "last_trading_day": window[-1] if window else None}
    if not window:
        report["issues"].append("请求窗口没有官方交易日")
    calendar_ok = not report["issues"]
    calset = set(window)

    def series(code, adj, route, *, benchmark=False, first=None):
        overseas = route in OVERSEAS_ROUTES and not benchmark
        # 海外窗口前的原生 K 线参与 I-24 预热，也必须有真实 OHLC。
        lower = start.isoformat() if start else "0001-01-01"
        # I-20：D 只能用 date < D 的行情。窗口末尾未被消费的原生行不能证明可用性。
        raw, rows = input_rows(con, code, adj, window, start=start, end=end, overseas=overseas)
        alignable = sum(d > rows[0]["date"] for d in window) if overseas and rows else len(rows)
        by_date = {r["date"]: r for r in rows}
        # 容器从自己的已登记起点起检查；基准必须覆盖整个窗口，含首尾。
        first = min(filter(None, [first, raw[0]["date"] if raw else None]), default=lower)
        expected = window if benchmark else [d for d in window if d >= first]
        missing = [] if overseas else [d for d in expected if d not in by_date or not _positive(by_date[d]["close"])]
        bad_close = [r["date"] for r in rows if not _positive(r["close"])]
        bad_ohl = [r["date"] for r in rows if not all(_positive(r[k]) for k in ("open", "high", "low"))]
        wrong_source = [r["date"] for r in rows if r["source"] != route]
        issues = []
        if not rows:
            issues.append("D−1 边界内无可用原生行情，无法对齐研究窗口" if overseas else "无窗口内真实行情")
        if missing:
            issues.append(f"缺交易日收盘 {len(missing)} 日")
        if bad_close:
            issues.append(f"无效收盘 {len(bad_close)} 行")
        if wrong_source:
            issues.append(f"来源与 coverage 不符 {len(wrong_source)} 行")
        close_ready = calendar_ok and bool(rows) and not issues
        return {"code": code, "adj": adj, "route": route, "raw_rows": len(raw), "view_rows": len(rows),
                "alignable_rows": alignable,
                "native_warmup_rows": sum(r["date"] < lower for r in rows) if overseas else 0,
                "unavailable_native_dates": [r["date"] for r in raw if not window or r["date"] >= window[-1]] if overseas else [],
                "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
                "excluded_non_trading_dates": [r["date"] for r in raw if not overseas and cal
                                               and cal[0] <= r["date"] <= cal[-1] and r["date"] not in calset],
                "outside_trusted_calendar_dates": [r["date"] for r in raw if not overseas
                                                   and (not cal or not cal[0] <= r["date"] <= cal[-1])],
                "missing_close_dates": missing, "invalid_close_dates": bad_close,
                "missing_ohl_dates": bad_ohl, "source_mismatch_dates": wrong_source,
                "close_ready": close_ready, "research_ready": close_ready and not bad_ohl,
                "issues": issues + ([f"策略缺真实 OHLC {len(bad_ohl)} 行"] if bad_ohl else [])}

    bench = series(BENCH_CODE, "raw", "csi", benchmark=True)
    report["benchmark"] = bench
    report["benchmark_ready"] = bench["close_ready"]
    covs = {c["theme_id"]: c for c in DB.read_coverage(con)}
    uni = {r["theme_id"]: json.loads(r["row"]) for r in con.execute("SELECT theme_id, row FROM universe ORDER BY ord")}
    required = {tid for tid, row in uni.items() if row.get("status") in PANEL_STATUSES}
    required.update(tid for tid, row in covs.items() if row.get("status") in PANEL_STATUSES)
    if not required:
        report["issues"].append("没有声明的研究容器")
    for tid in sorted(required):
        c = covs.get(tid, {})
        item = series(c.get("series_code", ""), c.get("series_adj", ""), c.get("route_used", ""),
                      first=c.get("first_date"))
        item["container"] = c.get("container") or uni.get(tid, {}).get("theme", tid)
        if not c or c.get("status") not in PANEL_STATUSES or c.get("error"):
            item["issues"].append(c.get("error") or "缺有效研究 coverage")
            item["research_ready"] = False
        report["containers"][tid] = item
    report["research_ready"] = (report["benchmark_ready"] and not report["issues"] and bool(required)
                                and all(c["research_ready"] for c in report["containers"].values()))
    return report


def preflight(db: Path, end: date, *, start: date | None = None) -> dict:
    """market 或 package 的只读质量报告；包的来源/哈希复验仍由 verify/build 负责。"""
    con = DB.connect(db, readonly=True)
    try:
        con.execute("BEGIN")
        return inspect(con, end, start=start)
    finally:
        con.close()
