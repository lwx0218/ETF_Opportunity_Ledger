"""R3 → V1 的数据接口约定与校验。

输入是长表，一行 = 一个容器一个交易日：

    date        交易日（datetime64）
    container   容器名（研究池主题）
    open/high/low/close   后复权（含分红再投）的指数点位，同一容器口径一致
    state       形态状态代码，见 config.STATE_NAMES（R3 实现）
    rs_1m       近 1 月相对强弱：21 日收益 − 基准 21 日收益（R3 实现；横截面排名只看相对大小）
    atr20       ATR20 = 真实波幅的 20 日简单均值（与 etf_probe.py ATR14 同一算法，见 reference_atr）
    z_month     仅在该容器每月最后一个交易日有值：(月末收盘 − 前 20 个已完成月末收盘均值) / 其标准差
    data_hole   0 / 1；1 = 海外容器连续平盘数到第 5 行起（连续 ≥ 5 个 A 股交易日没有新 K 线，I-25），这些行不产生入场信号。
                缺这一列直接报错，不默认 0：默认 0 等于把断档当行情

基准另给一张表：date, hs300（I-18：沪深300 全收益指数 H00300，与策略的后复权口径一致）。
所有指标只能用 t 日及以前的数据——这是 R3 的责任，本模块只做形状校验。
两张表都来自指标层 build 产出的库 panel-D.sqlite（panel、bench 两表，replan §11），用 read_table 读。
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .config import STATE_NAMES

REQUIRED = ["date", "container", "open", "high", "low", "close", "state", "rs_1m", "atr20", "z_month", "data_hole"]


NUMERIC = ["open", "high", "low", "close", "rs_1m", "atr20", "z_month", "hs300", "hs300_open"]


class PanelError(ValueError):
    pass


def read_table(path, table: str) -> pd.DataFrame:
    """build 产出的面板库（panel-D.sqlite）里的 panel 或 bench 表。只读打开；NULL 读成 NaN，与旧 CSV 读法同一口径。"""
    if table not in ("panel", "bench"):
        raise PanelError(f"未知的表 {table}")
    path = Path(path)
    if not path.exists():
        raise PanelError(f"{path} 不存在")
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY " + ("date, container" if table == "panel" else "date"), con)
    except Exception as e:  # noqa: BLE001 — 不是面板库
        raise PanelError(f"{path} 读不出 {table} 表：{e}") from e
    finally:
        con.close()
    for c in NUMERIC:
        if c in df:
            df[c] = pd.to_numeric(df[c]).astype(float)
    if "state" in df:
        df["state"] = df["state"].where(df["state"].notna(), np.nan)
    return df


def content_sha256(path) -> str:
    """面板库（panel、bench、meta 三表）内容的规范化哈希：同一份数据在任何机器、任何 SQLite 版本上都是同一个值。"""
    from src.data.db import content_sha256 as _content
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return _content(con, {"meta": "key", "bench": "date", "panel": "date, container"})
    finally:
        con.close()


def read_table_csv(path) -> pd.DataFrame:
    """迁移期对照用的旧 CSV 读法（replan §11：合并后删）。只读，不再有代码写 CSV 面板。"""
    return pd.read_csv(path)


def validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in panel.columns]
    if missing:
        raise PanelError(f"缺少列：{missing}")
    p = panel[REQUIRED].copy()
    p["date"] = pd.to_datetime(p["date"])
    if p.duplicated(["date", "container"]).any():
        raise PanelError("存在重复的 (date, container)")
    if not p["data_hole"].isin([0, 1]).all():
        raise PanelError("data_hole 只能是 0 / 1（I-25），不能为空")
    p["data_hole"] = p["data_hole"].astype(int)
    bad = set(p["state"].dropna().unique()) - set(STATE_NAMES)
    if bad:
        raise PanelError(f"未知的形态状态代码：{sorted(bad)}")
    px = p[["open", "high", "low", "close"]]
    ok = px.notna().all(axis=1)
    viol = ok & ((p["high"] < px.max(axis=1) - 1e-9) | (p["low"] > px.min(axis=1) + 1e-9))
    if viol.any():
        raise PanelError(f"OHLC 不一致 {int(viol.sum())} 行")
    if (p.loc[ok, ["open", "high", "low", "close"]] <= 0).any().any():
        raise PanelError("价格必须为正（腾讯减法前复权会出现负价，不能用）")
    return p.sort_values(["date", "container"]).reset_index(drop=True)


def validate_bench(bench: pd.DataFrame) -> pd.DataFrame:
    if not {"date", "hs300"} <= set(bench.columns):
        raise PanelError("基准表需要 date, hs300 两列")
    b = bench[["date", "hs300"]].copy()
    b["date"] = pd.to_datetime(b["date"])
    return b.sort_values("date").drop_duplicates("date").set_index("date")["hs300"]


def reference_atr(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """单个容器的参考 ATR（简单均值口径），供 R3 自检与测试使用。"""
    c, h, l = df["close"], df["high"], df["low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def hole_runs(panel: pd.DataFrame) -> pd.DataFrame:
    """各容器 data_hole = 1 的连续段（起止日期、行数），供 check 打印与 V1 报告列出（I-25）。"""
    rows = []
    for c, g in panel.sort_values("date").groupby("container"):
        h = g["data_hole"].to_numpy()
        d = g["date"].to_numpy()
        k = 0
        while k < len(h):
            if h[k]:
                j = k
                while j + 1 < len(h) and h[j + 1]:
                    j += 1
                rows.append(dict(container=c, first=pd.Timestamp(d[k]).date(), last=pd.Timestamp(d[j]).date(), rows=j - k + 1))
                k = j + 1
            else:
                k += 1
    return pd.DataFrame(rows, columns=["container", "first", "last", "rows"])


def wide(panel: pd.DataFrame, col: str) -> pd.DataFrame:
    return panel.pivot(index="date", columns="container", values=col).sort_index()


def ew_daily_returns(panel: pd.DataFrame) -> pd.Series:
    """等权组合日收益（I-10：每日再平衡，取当日有收盘的容器的日收益均值）。"""
    close = wide(panel, "close")
    r = close.pct_change(fill_method=None)
    return r.mean(axis=1, skipna=True).fillna(0.0)
