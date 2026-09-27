"""入场信号（prereg-v1 §3）。只用 t 日收盘及以前的面板字段；成交在 t+1 开盘（engine）。"""
import numpy as np
import pandas as pd

from .config import Params


def rs_top_flags(panel: pd.DataFrame, p: Params) -> pd.Series:
    """横截面：当日有 rs_1m 的容器按 rs_1m 从高到低排名，名次 / 容器数 ≤ rs_top_pct 为前 20%（I-04）。"""
    g = panel.groupby("date")["rs_1m"]
    n = g.transform("count")
    rk = g.rank(ascending=False, method="first")
    return ((rk / n) <= p.rs_top_pct + 1e-12) & panel["rs_1m"].notna()


def breakout_signals(panel: pd.DataFrame, p: Params) -> pd.DataFrame:
    """主分支：状态 ∈ 可进态 且 rs_1m 前 20% 且 该容器 20 个交易日内没有触发过（I-05：按信号计，不论是否成交）。"""
    df = panel.copy()
    df["rs_top"] = rs_top_flags(df, p)
    cand = df[df["state"].isin(p.entry_states) & df["rs_top"] & df["atr20"].gt(0)]
    dates = pd.Index(sorted(panel["date"].unique()))
    pos = pd.Series(np.arange(len(dates)), index=dates)
    keep = []
    for _, g in cand.sort_values("date").groupby("container"):
        last = None
        for i, t in zip(g.index, pos.loc[g["date"]].to_numpy()):
            if last is None or t - last > p.cooldown_days:
                keep.append(i)
                last = t
    out = cand.loc[sorted(keep)].copy()
    out["branch"] = "突破"
    out["priority"] = -out["rs_1m"]                   # I-07：同日多个信号时 rs_1m 高者优先
    return out


def panic_signals(panel: pd.DataFrame, p: Params) -> pd.DataFrame:
    """次分支：月末 z ≤ −2（z 由 R3 按前 20 个已完成月末计算，只在月末行有值）。"""
    out = panel[panel["z_month"].le(p.z_threshold) & panel["atr20"].gt(0)].copy()
    out["branch"] = "恐慌"
    out["priority"] = 1e6 + out["z_month"]           # I-07：排在突破之后；越超跌越优先
    return out


def all_signals(panel: pd.DataFrame, p: Params, start=None, end=None) -> pd.DataFrame:
    s = pd.concat([breakout_signals(panel, p), panic_signals(panel, p)], ignore_index=True)
    if start is not None:
        s = s[s["date"] >= pd.Timestamp(start)]
    if end is not None:
        s = s[s["date"] <= pd.Timestamp(end)]
    s["stop_level"] = s["close"] - p.stop_atr * s["atr20"]
    cols = ["date", "container", "branch", "state", "close", "atr20", "rs_1m", "z_month", "stop_level", "priority"]
    return s[cols].sort_values(["date", "priority", "container"]).reset_index(drop=True)
