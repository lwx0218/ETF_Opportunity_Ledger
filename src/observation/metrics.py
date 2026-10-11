"""Causal observation qualifications around the existing indicator functions.

Missing rows stay on the official calendar. No price repair, candle expansion,
volume fabrication, or state-machine restart is permitted here.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.indicators.metrics import atr20, rs_1m, z_month
from src.indicators.states import form_states

STATE_LABELS = {"POP": "启动", "XB": "回踩", "BNB": "平台突破", "REV": "超跌反弹",
                "EXH": "过热", "DROP": "破位", "XBD": "遇阻", "BNBD": "阴跌",
                "TREND_UP": "上升中", "TREND_DOWN": "下跌中", "NEUTRAL": "无趋势"}
OVERSEAS = {"yahoo", "stooq", "eia"}
NUMERIC = ("open", "high", "low", "close", "volume", "amount")


def positive(value):
    return isinstance(value, (int, float, np.number)) and math.isfinite(value) and value > 0


def numeric(value):
    return float(value) if isinstance(value, (int, float, np.number)) and math.isfinite(value) else None


def frame(rows):
    out = pd.DataFrame(rows, columns=("date", *NUMERIC, "source", "fetched_at"))
    out["date"] = pd.to_datetime(out["date"])
    for key in NUMERIC:
        out[key] = pd.to_numeric(out[key], errors="coerce").astype(float)
    return out


def candle_reason(row):
    if not positive(row.get("close")):
        return "缺少正且有限的真实收盘"
    if not all(positive(row.get(k)) for k in ("open", "high", "low")):
        return "缺少真实 OHL；不得以收盘补齐"
    if row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(row["open"], row["close"]):
        return "原始 OHLC 包络异常；保留缺口，等待源证据裁定"
    return None


def native_frame(raw, identity, cal, day, *, declared_first=None):
    """Cut off before selecting any auxiliary input. Keep domestic calendar gaps."""
    overseas = identity["source"] in OVERSEAS
    selected = raw[raw["date"] < day] if overseas else raw[raw["date"] <= day]
    if overseas:
        return selected.copy().reset_index(drop=True)
    selected = selected[selected["date"].isin(cal)]
    if selected.empty:
        return selected.copy().reset_index(drop=True)
    first = selected["date"].min()
    if declared_first:
        first = min(first, pd.Timestamp(declared_first))
    dates = cal[(cal >= first) & (cal <= day)]
    return selected.set_index("date").reindex(dates).rename_axis("date").reset_index()


def aligned_frame(native, cal, source):
    """Attach native identity to the A-share grid; overseas D consumes date < D."""
    if source not in OVERSEAS:
        out = native.set_index("date").reindex(cal).rename_axis("date").reset_index()
        out["native_date"] = out["date"].where(out["source"].notna())
        out["stale_days"], out["data_hole"] = 0, 0
        return out
    dates = native["date"].to_numpy()
    positions = np.searchsorted(dates, cal.to_numpy(), side="left") - 1
    out = native.reindex(positions).reset_index(drop=True).rename(columns={"date": "native_date"})
    out["date"] = cal
    runs = pd.Series(positions)
    stale = runs.groupby(runs.ne(runs.shift()).cumsum()).cumcount().where(runs >= 0, 0)
    out["stale_days"] = stale
    out["data_hole"] = (stale >= 5).astype(int)
    return out


def choose_volume(native, price_raw, identity, price_code, day):
    """I-21 cutoff belongs to each column, not the page's final observation day."""
    out = native.copy()
    # Invalid source values are absent inputs, not zero volume. A negative mean
    # could otherwise make a negative current volume satisfy the surge test.
    out["volume"] = out["volume"].where(np.isfinite(out["volume"]) & (out["volume"] > 0))
    if native.empty:
        return out, "none"
    # Missing calendar rows are not native observations and must not change I-21.
    actual = native["source"].notna()
    own = native.loc[actual, "volume"]
    if len(own) and (~(np.isfinite(own) & (own > 0))).mean() <= 0.5:
        return out, "self"
    if identity["code"] == price_code or price_raw.empty:
        return out, "none"
    pv = price_raw[(price_raw["date"] < day) if identity["source"] in OVERSEAS else (price_raw["date"] <= day)]
    # This independently registered candidate has deliberately unverified units
    # and is never approved as a borrowed state input.
    pv = pv[pv["source"] != "tencent_price_index_offline"]
    got = native["date"].map(pv.set_index("date")["volume"])
    if not (np.isfinite(got) & (got > 0)).any():
        return out, "none"
    out["volume"] = got.where(np.isfinite(got) & (got > 0))
    return out, "price_version"


def calculate(native, aligned, benchmark, cal, identity, volume_native, base_reason=None, *, benchmark_source="csi", prefix_reason=None):
    """Return values plus explicit reasons/windows; no hidden missing-data repair."""
    day = cal[-1]
    final = aligned.iloc[-1]
    native_day = final.get("native_date")
    stamp = native_day.date().isoformat() if pd.notna(native_day) else None
    source_match = native["source"].eq(identity["source"])
    close_good = np.isfinite(native["close"]) & (native["close"] > 0) & source_match
    ohlc = native[["open", "high", "low", "close"]]
    candles = (np.isfinite(ohlc).all(axis=1) & (ohlc > 0).all(axis=1)
               & native["high"].ge(ohlc.max(axis=1)) & native["low"].le(ohlc.min(axis=1)) & source_match)
    hole = bool(final["data_hole"])
    common = base_reason or ("海外原生行情连续第 5 个 A 股交易日起未更新，data_hole=1" if hole else None)
    result = {}

    def add(name, value, reason, *, start=None, points=0, required=None, **extra):
        if isinstance(value, (int, float, np.number)):
            value = numeric(value)
        result[name] = {"value": value, "available": value is not None, "reason": reason,
                        "native_date": stamp, "fetched_at": final.get("fetched_at") if pd.notna(final.get("fetched_at")) else None,
                        "window": {"start": None if pd.isna(start) else str(start.date()) if isinstance(start, pd.Timestamp) else start,
                                   "end": day.date().isoformat(), "points": points, "required": required}, **extra}

    present = final.get("source") == identity["source"] and positive(final.get("close"))
    close_reason = base_reason or (None if present else "该观察日缺真实收盘或来源不符")
    add("close", final["close"] if not close_reason else None, close_reason, start=native_day, points=int(present), required=1,
        stale_days=int(final["stale_days"]), data_hole=int(hole))

    # Require every one of the 22 aligned points. pct_change alone only checks
    # endpoints and would quietly accept an interior hole.
    window = aligned.tail(22)
    bench = benchmark.reindex(pd.DatetimeIndex(window["date"]))
    own_good = np.isfinite(window["close"]) & (window["close"] > 0) & window["source"].eq(identity["source"]) & window["data_hole"].eq(0)
    bench_good = np.isfinite(bench) & (bench > 0)
    rs_reason = common
    if not rs_reason and len(window) < 22:
        rs_reason = "21 日相对收益需要 22 个官方对齐观察点，预热不足"
    if not rs_reason and not own_good.all():
        rs_reason = "21 日窗口内缺合格收盘；不压缩缺日或数据断档"
    if not rs_reason and not bench_good.all():
        rs_reason = "21 日窗口缺 H00300 全收益基准收盘；不退回绝对收益"
    rs = rs_1m(window["close"], window["date"], bench).iloc[-1] if not rs_reason else None
    add("rs_1m", rs, rs_reason, start=window.iloc[0]["date"], points=int(own_good.sum()), required=22,
        benchmark={"code": "H00300", "adj": "raw", "source": benchmark_source, "price_basis": "全收益指数"})

    recent = native.tail(20)
    atr_reason = common
    if not atr_reason and len(recent) < 20:
        atr_reason = "ATR20 需要 20 根原生 K 线，预热不足"
    if not atr_reason and not candles.tail(20).all():
        atr_reason = "ATR20 依赖窗口缺真实 OHLC 或存在包络/来源异常"
    if not atr_reason and len(native) > 20 and not close_good.iloc[-21]:
        atr_reason = "ATR20 的前一根真实收盘缺失"
    add("atr20", atr20(native).iloc[-1] if not atr_reason else None, atr_reason,
        start=recent.iloc[0]["date"] if len(recent) else None, points=int(candles.tail(20).sum()), required=20)

    state_reason = common or prefix_reason
    if not state_reason and len(native) < 70:
        state_reason = "形态需要 70 根合格原生行，覆盖 SMA50 与前 20 行 up_recent；预热不足"
    if not state_reason and not close_good.all():
        bad_dates = native.loc[~close_good, "date"]
        state_reason = (f"EMA 原生历史有 {len(bad_dates)} 行收盘或来源缺口（首日 {bad_dates.iloc[0].date()}）；"
                        "不修补或重置 EMA 起点")
    if not state_reason and not candles.tail(70).all():
        bad_dates = native.tail(70).loc[~candles.tail(70), "date"]
        state_reason = f"最近 70 根原生行有 {len(bad_dates)} 行 OHLC/包络异常（首日 {bad_dates.iloc[0].date()}）"
    state = form_states(volume_native).iloc[-1] if not state_reason else None
    volume_limited = not (np.isfinite(volume_native["volume"].tail(20)) & (volume_native["volume"].tail(20) > 0)).all()
    note = "成交量受限的形态；四种放量状态不可完整判定" if volume_limited else None
    add("state", state["state"] if state is not None else None, state_reason or note,
        start=native.iloc[0]["date"] if len(native) else None, points=int(candles.sum()), required=70,
        state_label=STATE_LABELS.get(state["state"]) if state is not None else None,
        qualification="volume_limited" if volume_limited else "complete")
    ext_reason = state_reason or ("ATR14 非正或非有限，ext 不可用" if not positive(state["atr14"]) else None)
    add("ext", state["ext"] if not ext_reason else None, ext_reason,
        start=native.iloc[0]["date"] if len(native) else None, points=int(candles.sum()), required=70,
        denominator="ATR14")
    return result


def monthly(aligned, full_cal, day, source):
    """Completed official month ends, including empty months (never compress)."""
    periods = full_cal.to_period("M")
    # Determine neighbours explicitly: the final calendar month is unconfirmed.
    ends = full_cal[:-1][(periods[:-1] != periods[1:]) & (full_cal[:-1] <= day)]
    if not len(ends):
        return {"value": None, "available": False, "reason": "官方日历尚未证明一个已完成月末", "value_date": None,
                "window": {"start": None, "end": None, "points": 0, "required": 21}}
    dates = pd.DatetimeIndex(ends)
    rows = aligned.set_index("date").reindex(dates)
    valid = np.isfinite(rows["close"]) & (rows["close"] > 0) & rows["source"].eq(source) & rows["data_hole"].eq(0)
    closes = rows["close"].where(valid)
    window = closes.tail(21)
    reason = None
    if len(window) < 21:
        reason = "月末 z 需要当月及此前 20 个已完成月末，样本不足"
    elif window.isna().any():
        reason = "21 个月末窗口缺真实收盘；缺月不压缩"
    elif window.iloc[:-1].std() == 0:
        reason = "此前 20 个月末标准差为零"
    value = None
    if not reason:
        value = numeric(z_month(closes.reset_index(drop=True), pd.Series(dates), day.date(), trading_days=full_cal).iloc[-1])
    return {"value": value, "available": value is not None, "reason": reason, "value_date": dates[-1].date().isoformat(),
            "native_date": str(rows.iloc[-1]["native_date"].date()) if pd.notna(rows.iloc[-1]["native_date"]) else None,
            "fetched_at": rows.iloc[-1]["fetched_at"] if pd.notna(rows.iloc[-1]["fetched_at"]) else None,
            "window": {"start": window.index[0].date().isoformat(), "end": dates[-1].date().isoformat(),
                       "points": int(window.notna().sum()), "required": 21}}
