"""A 股交易日历文件 data/calendar/sse-trading-days.csv（v1.1-e）。由 astra 用深交所日历接口生成、每年补一次，随研究数据包交付；
一行一个交易日（YYYY-MM-DD 或 YYYYMMDD，可有表头）。没有文件时各处退回「下一个工作日」规则。"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "data" / "calendar" / "sse-trading-days.csv"


def _parse(tok: str) -> date | None:
    tok = tok.strip().strip('"')
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(tok, fmt).date()
        except ValueError:
            continue
    return None


def load_trading_days(path: Path | None = CALENDAR) -> pd.DatetimeIndex | None:
    if path is None or not Path(path).exists():
        return None
    days = {d for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if (d := _parse(line.split(",")[0]))}
    return pd.DatetimeIndex(sorted(days)) if days else None


def next_trading_day(d: date, trading_days: pd.DatetimeIndex | None) -> date | None:
    """日历里 d 之后的第一个交易日；日历没覆盖到则返回 None（调用方退回工作日规则）。"""
    if trading_days is None:
        return None
    later = trading_days[trading_days > pd.Timestamp(d)]
    return later[0].date() if len(later) else None
