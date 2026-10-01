"""A 股交易日历（v1.1-e）：data/market.sqlite 的 calendar 表（replan §11）。astra 用深交所日历接口生成清单文件、每年补一次，
`python -m src.data calendar <文件>` 校验后写入库；`package` 把它复制进研究数据包。库里没有日历（表空）时各处退回「下一个工作日」规则。"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.data import db as DB

MAX_GAP_DAYS = 14          # 相邻交易日最长间隔：春节 / 国庆休市连周末约 11 天


def _parse(tok: str) -> date | None:
    tok = tok.strip().strip('"')
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(tok, fmt).date()
        except ValueError:
            continue
    return None


def check_days(days, name: str) -> pd.DatetimeIndex:
    """排序去重后的交易日；含周末、没有日期、相邻两天间隔超过 MAX_GAP_DAYS（中间缺一段）即报错（ValueError）。"""
    days = sorted(set(pd.Timestamp(d).date() for d in days))
    if not days:
        raise ValueError(f"{name} 里没有交易日")
    for d in days:
        if d.weekday() >= 5:
            raise ValueError(f"{name}：{d} 是周末，混进了非交易日")
    idx = pd.DatetimeIndex(days)
    gaps = (idx[1:] - idx[:-1]).days
    if len(gaps) and gaps.max() > MAX_GAP_DAYS:
        k = int(gaps.argmax())
        raise ValueError(f"{name} 在 {idx[k].date()} 与 {idx[k + 1].date()} 之间缺了一段（间隔 {gaps.max()} 天）")
    return idx


def read_calendar_file(path: Path) -> pd.DatetimeIndex:
    """astra 生成的清单：一行一个交易日（YYYY-MM-DD 或 YYYYMMDD，可有表头）。不像交易日历就报错（ValueError），不静默跳过：
    一行多列（例如原样导出的 monthList 带开市标志）、第一行以外有非日期行、含周末、中间缺一段、没有任何日期。"""
    name = Path(path).name
    days = []
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
        days.append(d)
    return check_days(days, name)


def load_trading_days(source=DB.MARKET_DB) -> pd.DatetimeIndex | None:
    """库（market.sqlite 或研究数据包）里的交易日历。source 为库路径或已打开的连接；库不存在或 calendar 表为空时返回 None
    （各处退回工作日规则）。表里的日期不像交易日历（中间缺一段）时报错（ValueError），不静默退回。"""
    if isinstance(source, sqlite3.Connection):
        con, own = source, False
    else:
        if source is None:
            return None
        DB.refuse_default_in_tests(source, DB.MARKET_DB)
        if not Path(source).exists():
            return None
        con, own = DB.connect(source, readonly=True), True
    try:
        days = [r[0] for r in con.execute("SELECT date FROM calendar ORDER BY date")]
    finally:
        if own:
            con.close()
    return check_days(days, "交易日历（calendar 表）") if days else None


def next_trading_day(d: date, trading_days: pd.DatetimeIndex | None) -> date | None:
    """日历里 d 之后的第一个交易日；日历没覆盖到则返回 None（调用方退回工作日规则）。"""
    if trading_days is None:
        return None
    later = trading_days[trading_days > pd.Timestamp(d)]
    return later[0].date() if len(later) else None
