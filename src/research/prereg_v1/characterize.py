"""§10 第 2 步：形态状态的描述性刻画（不建规则）。

I-14：只在设计期（≤ 2015-12-31）上做，避免在冻结样本外跑之前先看到 2016 年以后的数据。
I-15：前向窗口 20 个交易日，用「对当日等权的超额」；区分度判据 = 可进态均值 − 非可进态均值，
      按自然季度做块自助（bootstrap；20 日窗口会跨月，按月分块会低估相关、区间偏窄），
      95% 区间下界 > 0 才算「分得开」。
I-26：断档行（data_hole = 1）不是行情，按缺数据处理：不作样本、不作别的样本的前向终点、不进当日等权——
      结果与把这些行从面板里删掉完全相同。
"""
import numpy as np
import pandas as pd

from .config import DANGER_STATES, ENTRY_STATES, Params


def state_class(s: str) -> str:
    if s in ENTRY_STATES:
        return "可进"
    if s in DANGER_STATES:
        return "危险"
    if s == "REV":
        return "超跌反弹"
    return "中性"


def forward_excess(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    close = panel.pivot(index="date", columns="container", values="close").sort_index()
    hole = panel.pivot(index="date", columns="container", values="data_hole").reindex_like(close)
    close = close.where(hole.eq(0))                          # I-26：断档行按缺数据处理
    fwd = close.shift(-horizon) / close - 1
    ex = fwd.sub(fwd.mean(axis=1), axis=0)
    long = ex.stack().rename("fwd_excess").reset_index()
    idx = close.index
    fwd_end = pd.Series(list(idx[horizon:]) + [pd.NaT] * horizon, index=idx, name="fwd_end")
    long = long.merge(fwd_end, left_on="date", right_index=True, how="left")
    return panel[["date", "container", "state"]].merge(long, on=["date", "container"], how="inner")


def characterize(panel: pd.DataFrame, p: Params, end, seed: int = 0) -> dict:
    df = forward_excess(panel, p.char_horizon)
    df = df[df["fwd_end"] <= pd.Timestamp(end)].dropna(subset=["fwd_excess", "state"])   # 前向窗口也不越过设计期
    df["class"] = df["state"].map(state_class)
    agg = lambda g: pd.Series({"n": len(g), "mean": g.mean(), "median": g.median(), "share_pos": (g > 0).mean()})
    by_state = df.groupby("state")["fwd_excess"].apply(agg).unstack()
    by_class = df.groupby("class")["fwd_excess"].apply(agg).unstack()

    df["block"] = df["date"].dt.to_period("Q")
    df["is_entry"] = df["class"].eq("可进")
    m = df.groupby(["block", "is_entry"])["fwd_excess"].agg(["sum", "count"]).unstack(fill_value=0)
    months = m.index.to_numpy()
    s_in, n_in = m[("sum", True)].to_numpy(), m[("count", True)].to_numpy()
    s_out, n_out = m[("sum", False)].to_numpy(), m[("count", False)].to_numpy()
    diff = s_in.sum() / max(n_in.sum(), 1) - s_out.sum() / max(n_out.sum(), 1)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(p.char_bootstrap):
        idx = rng.integers(0, len(months), len(months))
        a, b = n_in[idx].sum(), n_out[idx].sum()
        if a and b:
            boots.append(s_in[idx].sum() / a - s_out[idx].sum() / b)
    lo, hi = np.percentile(boots, [2.5, 97.5]) if boots else (np.nan, np.nan)
    return dict(by_state=by_state, by_class=by_class, diff_entry_minus_rest=float(diff),
                ci95=(float(lo), float(hi)), separable=bool(lo > 0), n_blocks=len(months))
