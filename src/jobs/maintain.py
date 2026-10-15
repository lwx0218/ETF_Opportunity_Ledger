"""--maintain-only 用的窄预检和执行 ETF 面板。不读研究池完整性，不生成候选。"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.data import db as DB
from src.indicators.build import BENCH_CODE, container_panel
from src.indicators.calendar import load_trading_days
from src.indicators.states import STATES


def open_cards(ledger) -> list[dict]:
    return [dict(row) for row in ledger.conn.execute(
        """SELECT c.id, c.container, c.instrument_code FROM cards c
           JOIN card_status s ON s.id = c.id
           WHERE c.sealed = 1 AND s.status IN ('候选', '当下', '过去')""")]


def _bars(con, code, source, end: date) -> pd.DataFrame:
    rows = con.execute(
        """SELECT date, open, high, low, close, volume FROM bars
           WHERE code = ? AND adj = 'raw' AND source = ? AND date <= ? ORDER BY date""",
        (code, source, end.isoformat())).fetchall()
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def execution_panel(db, cards: list[dict], end: date):
    """在场卡各自的执行 ETF（不复权）装成 DailyJob 现用的面板。基准仍是 H00300。"""
    con = DB.connect(db, readonly=True)
    try:
        con.execute("BEGIN")
        trading = load_trading_days(con)
        cov = {row["container"]: row for row in DB.read_coverage(con)}
        bench_raw = _bars(con, BENCH_CODE, "csi", end)
        if bench_raw.empty:
            empty = pd.DataFrame(columns=["date", "container", "open", "high", "low", "close", "state", "rs_1m", "atr20", "z_month", "data_hole"])
            return empty, pd.Series(dtype=float), pd.Series(dtype=float), trading
        frames = []
        for card in cards:
            meta = cov.get(card["container"]) or {}
            source = meta.get("exec_route") or "tencent_etf"
            code = card["instrument_code"]
            raw = _bars(con, code, source, end)
            if raw.empty and meta.get("exec_route") is None:
                raw = _bars(con, code, "tencent_etf", end)
            if raw.empty:
                continue
            piece = container_panel(raw, bench_raw.set_index("date")["close"] if len(bench_raw) else pd.Series(dtype=float),
                                    end, trading, compute_indicators=True)
            piece.insert(1, "container", card["container"])
            frames.append(piece)
        bench = bench_raw.set_index("date")["close"] if len(bench_raw) else pd.Series(dtype=float)
        opened = bench_raw.set_index("date")["open"] if len(bench_raw) else pd.Series(dtype=float)
        panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
            columns=["date", "container", "open", "high", "low", "close", "state", "rs_1m", "atr20", "z_month", "data_hole"])
        return panel, bench, opened.where(opened > 0), trading
    finally:
        con.close()


def preflight_open(day: str, cards: list[dict], panel: pd.DataFrame, bench: pd.Series,
                   trading, done: set[str]) -> list[str]:
    blocking = []
    dates = [] if trading is None else [item.date().isoformat() for item in trading]
    if day not in dates:
        blocking.append(f"{day} 不在官方交易日历")
    bench_days = {item.date().isoformat() for item in bench.index} if len(bench) else set()
    if day not in bench_days:
        blocking.append(f"{day} 基准 H00300 没有收盘")
    earlier = [item for item in dates if item < day]
    prev = earlier[-1] if earlier else None
    if done and prev and prev not in done and day not in done:
        blocking.append(f"漏跑 {prev}：先按顺序补跑，再跑 {day}")
    today = panel[panel["date"] == pd.Timestamp(day)] if len(panel) else panel
    for card in cards:
        rows = today[today["container"] == card["container"]] if len(today) else today
        if rows.empty:
            blocking.append(f"{card['container']} 执行 ETF {card['instrument_code']} 在 {day} 没有行情")
            continue
        row = rows.iloc[0]
        if row["state"] not in STATES or not np.isfinite(row["open"]) or not np.isfinite(row["close"]):
            blocking.append(f"{card['container']} 在 {day} 的执行 ETF 行情不足以记账")
    return blocking
