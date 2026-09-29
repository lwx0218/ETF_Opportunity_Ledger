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


MAX_GAP_DAYS = 14          # 相邻交易日最长间隔：春节 / 国庆休市连周末约 11 天


def load_trading_days(path: Path | None = CALENDAR) -> pd.DatetimeIndex | None:
    """没有文件返回 None（各处退回工作日规则）。文件在但不像交易日历就报错（ValueError），不静默退回：
    一行多列（例如原样导出的 monthList 带开市标志）、第一行以外有非日期行、含周末、相邻两天间隔超过 MAX_GAP_DAYS（中间缺一段）、
    没有任何日期。"""
    if path is None or not Path(path).exists():
        return None
    days, name = set(), Path(path).name
    lines = [x.strip() for x in Path(path).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    for k, line in enumerate(lines):
        cells = [c for c in line.split(",") if c.strip()]
        if len(cells) != 1:
            raise ValueError(f"{name} 第 {k + 1} 行「{line[:40]}」：应一行一个交易日")
        d = _parse(cells[0])
        if d is None:
            if k == 0:
                continue                                   # 表头
            raise ValueError(f"{name} 第 {k + 1} 行「{line[:40]}」不是日期")
        if d.weekday() >= 5:
            raise ValueError(f"{name} 第 {k + 1} 行 {d} 是周末：文件里混进了非交易日")
        days.add(d)
    if not days:
        raise ValueError(f"{name} 里没有交易日")
    idx = pd.DatetimeIndex(sorted(days))
    gaps = (idx[1:] - idx[:-1]).days
    if len(gaps) and gaps.max() > MAX_GAP_DAYS:
        k = int(gaps.argmax())
        raise ValueError(f"{name} 在 {idx[k].date()} 与 {idx[k + 1].date()} 之间缺了一段（间隔 {gaps.max()} 天）")
    return idx


def next_trading_day(d: date, trading_days: pd.DatetimeIndex | None) -> date | None:
    """日历里 d 之后的第一个交易日；日历没覆盖到则返回 None（调用方退回工作日规则）。"""
    if trading_days is None:
        return None
    later = trading_days[trading_days > pd.Timestamp(d)]
    return later[0].date() if len(later) else None
