"""ATR20、rs_1m、z_month。口径见 operations/planning/2026-09-27-prereg-v1-implementation-notes.md（I-02、B 节）。"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .calendar import next_trading_day


def atr20(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """真实波幅的 n 日简单均值（I-02；与 src/research/prereg_v1/panel.py: reference_atr 同一算法）。"""
    c, h, l = df["close"], df["high"], df["low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rs_1m(close: pd.Series, dates: pd.Series, bench: pd.Series, n: int = 21) -> pd.Series:
    """n 日收益 − 基准 n 日收益。基准取每个容器交易日当天或之前最近的一个收盘（只看过去），
    两者都按容器自己的交易日往回数 n 行。容器与基准同一交易日历时，结果与 etf_probe.build_panel 相同。"""
    b = bench.sort_index().reindex(pd.DatetimeIndex(dates), method="ffill")
    b = pd.Series(b.to_numpy(), index=close.index)
    return close.pct_change(n, fill_method=None) - b.pct_change(n, fill_method=None)


def _next_weekday(d: date) -> date:
    x = d + timedelta(days=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return x


def month_end_flags(dates: pd.Series, end: date, trading_days: pd.DatetimeIndex | None = None) -> pd.Series:
    """每月最后一个交易日为 True。下一行在新月份即为月末。最后一行：有交易日历文件且覆盖到它之后时，看日历里的下一个交易日
    是否进入新月份（v1.1-e，节假日跨月也能当天认出）；否则看下一个工作日是否进入新月份（月末落在周末当天能认出，
    停更的序列不会在月中冒出 z；月底最后一个工作日恰逢节假日的少数月份，要等下一行出现后才被认作月末）。"""
    d = pd.to_datetime(dates).reset_index(drop=True)
    per = d.dt.to_period("M")
    flag = per.ne(per.shift(-1))
    if len(d):
        last = d.iloc[-1].date()
        nxt = next_trading_day(last, trading_days) or _next_weekday(last)
        flag.iloc[-1] = last <= end and nxt.month != last.month
    return pd.Series(flag.to_numpy(), index=dates.index)


def z_month(close: pd.Series, dates: pd.Series, end: date, n: int = 20, trading_days: pd.DatetimeIndex | None = None) -> pd.Series:
    """只在月末行有值：(月末收盘 − 前 n 个已完成月末收盘的均值) / 其标准差（样本标准差），其余为空。
    与 src/research/characterize.py 同口径：mu = c.shift(1).rolling(n).mean()，sd = c.shift(1).rolling(n).std()。"""
    flag = month_end_flags(dates, end, trading_days)
    m = close[flag]
    mu = m.shift(1).rolling(n).mean()
    sd = m.shift(1).rolling(n).std()
    z = (m - mu) / sd
    out = pd.Series(np.nan, index=close.index)
    out[flag] = z
    return out
