"""Pure read model for the two observation pages.

The caller owns a SQLite read-only snapshot. This module only issues SELECTs;
it does not construct a market database, migrate, scan, or run research/build.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.data.universe import PANEL_STATUSES
from src.data.quality import inspect
from src.indicators.calendar import check_days
from .metrics import (OVERSEAS, aligned_frame, calculate, candle_reason,
                      choose_volume, frame, monthly, native_frame, numeric, positive)

BEIJING = ZoneInfo("Asia/Shanghai")
HISTORY_NOTE = "按当前库版本重建截至观察日的行情；获取时刻不代表历史可得时点，也不代表当时已扫描或作出判断。"
VOLUME_NOTE = "该接口及字段的成交量单位尚未有合格源证据（unit=unverified）；不画量柱、不借 ETF 量、不以价格乘量造金额。"


def rows(con, sql, args=()):
    cur = con.execute(sql, args)
    keys = [d[0] for d in cur.description]
    return [dict(zip(keys, row)) for row in cur]


def identity(code, adj, source, purpose, price_only):
    price_basis = ("价格指数（不含分红再投）" if source in {"csi", "eastmoney_index", "tencent_index", "tencent_price_index_offline"}
                   else "价格序列（不含分红再投）")
    basis = ("ETF 后复权全收益" if adj == "hfq" else "全收益指数") if price_only is False else (
        "ETF 不复权价格" if purpose == "execution" else price_basis)
    if price_only is None:
        basis = "价格/全收益口径未登记"
    return {"code": code or None, "adj": adj or None, "source": source or None,
            "purpose": purpose, "price_only": price_only, "price_basis": basis}


def _boolean(value):
    return True if str(value).lower() in ("1", "true") else False if str(value).lower() in ("0", "false") else None


def quality_summary(report):
    """The page needs readiness and reasons, not thousands of missing dates."""
    def series(item):
        keys = ("code", "adj", "route", "container", "raw_rows", "view_rows", "alignable_rows", "first", "last",
                "close_ready", "research_ready", "issues")
        counts = ("missing_close_dates", "invalid_close_dates", "missing_ohl_dates", "source_mismatch_dates",
                  "excluded_non_trading_dates", "outside_trusted_calendar_dates", "unavailable_native_dates")
        return {**{key: item[key] for key in keys if key in item},
                "counts": {key: len(item.get(key, [])) for key in counts}}
    keys = ("requested_window", "trusted_calendar_range", "effective_window", "calendar", "benchmark_ready", "research_ready", "issues")
    return {**{key: report[key] for key in keys}, "benchmark": series(report["benchmark"]),
            "containers": {tid: series(item) for tid, item in report["containers"].items()}}


def dates(cal, requested, now):
    """Do not substitute the last available bar for a requested observation day."""
    if now.tzinfo is None:
        raise ValueError("now 必须携带时区")
    local = now.astimezone(BEIJING)
    today = pd.Timestamp(local.date())
    completed = cal[(cal < today) | ((cal == today) & (local.time() >= time(15)))]
    current = completed[-1] if len(completed) and cal[0] <= today <= cal[-1] else None
    request = pd.Timestamp(requested) if requested is not None else today
    reason = None
    if request < cal[0] or request > cal[-1]:
        reason = "官方交易日历未覆盖请求日，无法确定有效观察日"
    elif requested is None and current is None:
        reason = "官方交易日历未覆盖当前日期，无法确定已完成交易日"
    elif request > today or (requested is not None and request in cal
                             and ((len(completed) and request > completed[-1]) or (request == today and local.time() < time(15)))):
        reason = "请求日尚未完成收盘，不能作未来观察"
    candidates = cal[cal <= request]
    effective = current if requested is None else (candidates[-1] if len(candidates) else None)
    return {"requested_date": request.date().isoformat(),
            "effective_date": effective.date().isoformat() if effective is not None and not reason else None,
            "completed_date": current.date().isoformat() if current is not None else None,
            "reason": reason}


class Observations:
    def __init__(self, con, cal, universe, coverages, *, synthetic=False):
        self.con, self.cal = con, cal
        self.universe, self.coverages = universe, coverages
        self.raw, self.computed = {}, {}
        bench = self.bars("H00300", "raw")
        self.benchmark_source = "demo_synthetic" if synthetic else "csi"
        valid = bench["source"].eq(self.benchmark_source) & np.isfinite(bench["close"]) & (bench["close"] > 0)
        self.benchmark = bench.set_index("date")["close"].where(valid.to_numpy())

    def bars(self, code, adj):
        key = code, adj
        if key not in self.raw:
            self.raw[key] = frame(rows(self.con, "SELECT date,open,high,low,close,volume,amount,source,fetched_at "
                                      "FROM bars WHERE code=? AND adj=? ORDER BY date", key))
        return self.raw[key]

    def selection(self, item, kind):
        cov = self.coverages.get(item["theme_id"], {})
        reason = None
        if kind == "research":
            ident = identity(cov.get("series_code"), cov.get("series_adj"), cov.get("route_used"), kind, _boolean(cov.get("price_only")))
            if not all(ident[k] for k in ("code", "adj", "source")) or cov.get("status") not in PANEL_STATUSES or cov.get("error"):
                reason = "缺有效选定研究 coverage" + (f"：{cov['error']}" if cov.get("error") else "")
        elif kind == "execution":
            ident = identity(cov.get("exec_code") or item.get("execution_fund_code"), "raw", cov.get("exec_route"), kind, True)
            if not ident["source"] or cov.get("exec_error"):
                reason = "执行 ETF 缺有效登记来源" + (f"：{cov['exec_error']}" if cov.get("exec_error") else "")
        elif kind == "price_candidate":
            code = cov.get("code") or item.get("research_index_code")
            raw = self.bars(code, "raw")
            source = raw.iloc[0]["source"] if len(raw) else None
            ident = identity(code, "raw", source, kind, True)
            if not len(raw) or (code == cov.get("series_code") and cov.get("series_adj") == "raw"):
                reason = "无独立未选价格候选；不得以其它序列替代选定研究"
        else:
            raise ValueError("series_kind 仅支持 research / execution / price_candidate")
        return ident, reason

    def one(self, item, day, kind="research"):
        key = item["theme_id"], day, kind
        if key in self.computed:
            return self.computed[key]
        ident, base_reason = self.selection(item, kind)
        cal = self.cal[self.cal <= day]
        raw = self.bars(ident["code"], ident["adj"])
        cov = self.coverages.get(item["theme_id"], {})
        declared_first = cov.get("first_date") if kind == "research" else cov.get("exec_first_date") if kind == "execution" else None
        native = native_frame(raw, ident, cal, day, declared_first=declared_first)
        aligned = aligned_frame(native, cal, ident["source"])
        price = self.bars(cov.get("code"), "raw") if kind == "research" else frame([])
        volumes, volume_source = choose_volume(native, price, ident, cov.get("code"), day)
        prefix_reason = None
        if ident["source"] in OVERSEAS and declared_first and len(native) and str(native.iloc[0]["date"].date()) > declared_first:
            prefix_reason = f"原生历史缺已登记起点 {declared_first} 至实际首行 {native.iloc[0]['date'].date()} 的前缀；不重置 EMA 起点"
        fields = calculate(native, aligned, self.benchmark, cal, ident, volumes, base_reason,
                           benchmark_source=self.benchmark_source, prefix_reason=prefix_reason)
        fields["state"]["volume_source"] = volume_source
        fields["ext"]["volume_source"] = volume_source
        if kind != "research":
            fields["rs_1m"].update(value=None, available=False, reason="相对收益与池内比较仅使用 coverage 选定研究序列")
            fields["rank"] = dict(fields["rs_1m"])
        z = monthly(aligned, self.cal, day, ident["source"])
        if base_reason:
            z.update(value=None, available=False, reason=base_reason)
        fields["z_month"] = z
        for value in fields.values():
            value.update(ident, theme_id=item["theme_id"], container=item.get("theme", item["theme_id"]),
                         observation_date=day.date().isoformat())
        # Legal exclusions are limited to the declared first-date boundary and
        # uninterrupted initial close warmup. Unknown holes still block ranks.
        exclusion = None
        first = cov.get("first_date") if kind == "research" else cov.get("exec_first_date")
        if first and first > day.date().isoformat() and not base_reason:
            exclusion = "早于已登记序列起点"
        elif first and first == day.date().isoformat() and ident["source"] in OVERSEAS and not base_reason:
            exclusion = "已登记原生起点尚未到 D−1 可用边界"
        elif first and len(native) and native.iloc[0]["date"].date().isoformat() == first:
            since = aligned[aligned["date"] > pd.Timestamp(first)] if ident["source"] in OVERSEAS else aligned[aligned["date"] >= pd.Timestamp(first)]
            if (not base_reason and len(since) < 22 and all(positive(v) for v in since["close"])
                    and since["source"].eq(ident["source"]).all() and since["data_hole"].eq(0).all()):
                exclusion = "已登记序列起点后的 21 日收益预热"
        result = {"theme_id": item["theme_id"], "container": item.get("theme", item["theme_id"]),
                  "line": item.get("line"), "status": item.get("status"), "identity": ident,
                  "native_date": fields["close"]["native_date"], "fields": fields, "volume_source": volume_source,
                  "data_hole": int(aligned.iloc[-1]["data_hole"]), "exclusion": exclusion,
                  "_native": native, "_raw": raw, "_aligned": aligned}
        self.computed[key] = result
        return result

    def section(self, day):
        items = [self.one(item, day) for item in self.universe]
        missing, excluded, valid = [], [], []
        for item in items:
            if item["fields"]["rs_1m"]["available"]:
                valid.append(item)
            elif item["exclusion"]:
                excluded.append({"theme_id": item["theme_id"], "reason": item["exclusion"]})
            else:
                missing.append({"theme_id": item["theme_id"], "reason": item["fields"]["rs_1m"]["reason"]})
        complete = not missing and bool(items)
        ranks = pd.Series([i["fields"]["rs_1m"]["value"] for i in valid]).rank(method="min", ascending=False)
        rank_map = {item["theme_id"]: int(rank) for item, rank in zip(valid, ranks)}
        for item in items:
            field = dict(item["fields"]["rs_1m"])
            rank = rank_map.get(item["theme_id"]) if complete else None
            field.update(value=rank, available=rank is not None,
                         reason=("池内存在未知缺口，完整横截面排名不可用" if not complete else item["exclusion"]),
                         method="min", pool=len(items), valid=len(valid))
            item["fields"]["rank"] = field
        return items, {"pool": len(items), "valid": len(valid), "missing": missing, "excluded": excluded,
                       "comparison_complete": complete, "method": "min", "order": "universe"}

    def detail(self, item, day, kind, chart_points):
        result = self.one(item, day, kind)
        native, ident = result["_native"], result["identity"]
        chart, gaps = [], []
        for row in native.tail(chart_points).to_dict("records"):
            match = row.get("source") == ident["source"]
            close_reason = None if match and positive(row["close"]) else "缺真实收盘或来源不符"
            ohlc_reason = candle_reason(row) if match else "该日没有所选来源的真实行情"
            if ohlc_reason:
                gaps.append({"date": row["date"].date().isoformat(), "reason": ohlc_reason})
            chart.append({"date": row["date"].date().isoformat(), "close": numeric(row["close"]) if not close_reason else None,
                          **{k: numeric(row[k]) if not ohlc_reason else None for k in ("open", "high", "low")},
                          "volume": None, "close_reason": close_reason, "ohlc_reason": ohlc_reason,
                          "volume_reason": VOLUME_NOTE, "source": row.get("source") if match else None,
                          "fetched_at": row["fetched_at"] if pd.notna(row["fetched_at"]) else None})
        options = [{"kind": k, "identity": self.selection(item, k)[0], "reason": self.selection(item, k)[1]}
                   for k in ("research", "execution", "price_candidate")]
        outside = result["_raw"]
        excluded = outside[(outside["date"] <= day) & ~outside["date"].isin(self.cal)] if ident["source"] not in OVERSEAS else outside.iloc[:0]
        return {"theme_id": item["theme_id"], "container": result["container"], "series_kind": kind, "identity": ident,
                "options": options, "fields": result["fields"], "chart": chart, "gaps": gaps,
                "native_date": result["native_date"], "data_hole": result["data_hole"],
                "volume_source": result["volume_source"], "volume": {"unit": "unverified", "reason": VOLUME_NOTE},
                "excluded_non_trading_dates": [d.date().isoformat() for d in excluded["date"]],
                "chart_window": {"points": len(chart), "start": chart[0]["date"] if chart else None,
                                 "end": chart[-1]["date"] if chart else None},
                "unavailable": {"nav": "缺匹配市场日期与发布时间的 NAV", "premium": "缺同口径价格与 NAV 配对",
                                "shares": "缺官方份额与单位证据", "amount": "缺经核定的原始成交额与单位",
                                "layers": "L1–L4 与源头/目的地判断尚缺冻结证据；价格排名不能替代"}}


def observe(con, requested_date: date | None = None, *, now: datetime | None = None,
            weeks: int = 12, theme_id: str | None = None, series_kind: str = "research", chart_points: int = 260) -> dict:
    """Read a caller-owned market-v1 snapshot and return JSON-safe observations."""
    if not 1 <= weeks <= 52 or not 1 <= chart_points <= 3000:
        raise ValueError("weeks 须为 1–52，chart_points 须为 1–3000")
    if series_kind not in ("research", "execution", "price_candidate"):
        raise ValueError("series_kind 仅支持 research / execution / price_candidate")
    universe = [json.loads(r["row"]) for r in rows(con, "SELECT row FROM universe ORDER BY ord")]
    universe = [r for r in universe if r.get("status") in PANEL_STATUSES]
    if theme_id is not None and theme_id not in {r["theme_id"] for r in universe}:
        raise ValueError("未知或不属于 retained/flagged 池的容器")
    coverages = {r["theme_id"]: r for r in rows(con, "SELECT * FROM coverage_latest")}
    raw_calendar = [r["date"] for r in rows(con, "SELECT date FROM calendar ORDER BY date")]
    synthetic = rows(con, "SELECT value FROM meta WHERE key='observation_mode'") == [{"value": "synthetic"}]
    result = {"requested_date": requested_date.isoformat() if requested_date else None,
              "effective_date": None, "completed_date": None, "calendar": None,
              "history_note": HISTORY_NOTE, "reason": None, "containers": [], "weeks": [], "rotation": [], "detail": None,
              "actual_data_end": None, "benchmark_ready": False, "research_ready": False, "quality": None,
              "synthetic": synthetic, "calendar_basis": "合成工作日，非官方交易日历" if synthetic else "官方 calendar",
              "comparison": {"pool": len(universe), "valid": 0, "missing": [], "excluded": [], "comparison_complete": False}}
    try:
        cal = check_days(raw_calendar, "官方交易日历")
    except ValueError as exc:
        result["reason"] = str(exc)
        return result
    result["calendar"] = {"first": raw_calendar[0], "last": raw_calendar[-1]}
    result.update(dates(cal, requested_date, now or datetime.now(BEIJING)))
    if not result["effective_date"]:
        return result
    day = pd.Timestamp(result["effective_date"])
    available = rows(con, "SELECT max(date) last FROM bars WHERE date<=?", (result["effective_date"],))[0]["last"]
    result["actual_data_end"] = available
    if synthetic:
        result["quality"] = {"note": "合成观察不证明正式研究可用", "benchmark_ready": False, "research_ready": False}
    else:
        quality = inspect(con, day.date())
        result.update(benchmark_ready=quality["benchmark_ready"], research_ready=quality["research_ready"], quality=quality_summary(quality))
    engine = Observations(con, cal, universe, coverages, synthetic=synthetic)
    current, comparison = engine.section(day)
    result["containers"] = [{k: v for k, v in item.items() if not k.startswith("_")} for item in current]
    result["comparison"] = comparison
    eligible = cal[cal <= day]
    week_days = pd.Series(eligible, index=eligible).groupby(eligible.to_period("W-FRI")).last().tail(weeks)
    sections = []
    calendar_weeks = cal.to_period("W-FRI")
    for week, effective in week_days.items():
        section, comp = engine.section(effective)
        official_week_end = cal[calendar_weeks == week][-1]
        partial = day < official_week_end or (cal[-1] < week.end_time.normalize() and day < week.end_time.normalize())
        result["weeks"].append({"date": effective.date().isoformat(),
                                "label": ("截至 " if partial else "") + effective.date().isoformat(),
                                "partial": bool(partial), "comparison": comp})
        sections.append(section)
    result["rotation"] = [{"theme_id": item["theme_id"], "container": item["container"],
                           "cells": [{"date": week["date"], "native_date": section[i]["native_date"],
                                      "state": section[i]["fields"]["state"], "rs_1m": section[i]["fields"]["rs_1m"],
                                      "rank": section[i]["fields"]["rank"], "data_hole": section[i]["data_hole"]}
                                     for week, section in zip(result["weeks"], sections)]}
                          for i, item in enumerate(current)]
    if universe:
        selected = next((u for u in universe if u["theme_id"] == theme_id), universe[0])
        result["detail"] = engine.detail(selected, day, series_kind, chart_points)
    return result
