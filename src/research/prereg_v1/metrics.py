"""衡量与验收（prereg-v1 §6、§9）。主指标是 R 倍数分布，胜率只作描述。"""
import numpy as np
import pandas as pd

from .config import Params
from .engine import Result
from .panel import ew_daily_returns


def r_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return dict(n=0)
    R = trades["R"].to_numpy()
    srt = np.sort(R)[::-1]
    out = dict(
        n=len(R), mean_R=R.mean(), median_R=float(np.median(R)),
        win_rate=float((R > 0).mean()),
        mean_win_R=float(R[R > 0].mean()) if (R > 0).any() else np.nan,
        mean_loss_R=float(R[R <= 0].mean()) if (R <= 0).any() else np.nan,
        share_gt_2R=float((R > 2).mean()), share_lt_neg1R=float((R < -1).mean()),
        max_R=float(R.max()), min_R=float(R.min()),
        n_open_at_end=int((trades["exit_reason"] == "期末未平").sum()),
    )
    for k in (1, 2, 3):
        out[f"mean_R_drop_best_{k}"] = float(srt[k:].mean()) if len(srt) > k else np.nan
    return out


def r_by(trades: pd.DataFrame, key) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    g = trades.groupby(key)["R"]
    return pd.DataFrame({"n": g.size(), "mean_R": g.mean(), "median_R": g.median()})


def max_drawdown(nav: pd.Series) -> float:
    return float((nav / nav.cummax() - 1).min())


def cagr(nav: pd.Series) -> float:
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 else np.nan


def yearly(nav: pd.Series) -> pd.Series:
    e = nav.groupby(nav.index.year).last()
    first = nav.iloc[0]
    return e / e.shift(1).fillna(first) - 1


def bench_nav(ret: pd.Series, index) -> pd.Series:
    r = ret.reindex(index).fillna(0.0)
    r.iloc[0] = 0.0
    return (1 + r).cumprod()


def avg_pairwise_corr(res: Result, panel: pd.DataFrame, window: int) -> float:
    """§8.3：同时持仓容器之间的平均两两相关（I-13：日收益、截至当日的 window 日滚动相关）。"""
    close = panel.pivot(index="date", columns="container", values="close").sort_index()
    r = close.pct_change(fill_method=None)
    held = res.holdings.gt(0)
    vals = []
    for d, row in held.iterrows():
        names = list(row.index[row.to_numpy()])
        if len(names) < 2:
            continue
        w = r.loc[:d, names].tail(window)
        cm = w.corr().to_numpy()
        iu = np.triu_indices(len(names), 1)
        v = cm[iu]
        v = v[np.isfinite(v)]
        if len(v):
            vals.append(v.mean())
    return float(np.mean(vals)) if vals else np.nan


def portfolio_stats(res: Result, panel: pd.DataFrame, hs300: pd.Series, p: Params) -> dict:
    nav = res.nav / res.nav.iloc[0]
    ew = bench_nav(ew_daily_returns(panel), nav.index)
    hs = hs300.reindex(nav.index).ffill()
    hs = hs / hs.iloc[0]
    y_s, y_e, y_h = yearly(nav), yearly(ew), yearly(hs)
    inv = float(res.invested.mean())
    turnover = float(res.trades["weight"].sum() * 2 / ((nav.index[-1] - nav.index[0]).days / 365.25)) if len(res.trades) else 0.0
    return dict(
        cagr=cagr(nav), cagr_after_index_discount=cagr(nav) - p.index_discount_per_year * inv,
        max_dd=max_drawdown(nav), ew_cagr=cagr(ew), ew_max_dd=max_drawdown(ew),
        hs300_cagr=cagr(hs), hs300_max_dd=max_drawdown(hs),
        excess_vs_ew_cagr=cagr(nav) - cagr(ew), excess_vs_hs300_cagr=cagr(nav) - cagr(hs),
        avg_invested=inv, turnover_per_year=turnover,
        yearly=pd.DataFrame({"策略": y_s, "等权": y_e, "沪深300": y_h, "对等权超额": y_s - y_e}),
    )


def acceptance(trades: pd.DataFrame, port: dict, p: Params) -> dict:
    """§9 五条。全部为 True 才算 v1 成立。"""
    rs = r_stats(trades)
    yt = port["yearly"]
    yrs = [y for y in p.accept_years if y in yt.index]
    pos_years = int((yt.loc[yrs, "对等权超额"] > 0).sum())
    checks = {
        "1 扣成本后期望 > +0.15R": rs.get("mean_R", -np.inf) > p.accept_mean_r,
        "2 去掉最好 3 笔后期望 > 0": (rs.get("mean_R_drop_best_3") or -np.inf) > 0,
        f"3 对等权超额 > 0 且逐年为正 ≥ {p.accept_min_positive_years}/{len(p.accept_years)}（实际 {pos_years}/{len(yrs)}）":
            port["excess_vs_ew_cagr"] > 0 and pos_years >= p.accept_min_positive_years,
        "4 最大回撤不深于等权": port["max_dd"] >= port["ew_max_dd"],
        f"5 交易数 ≥ {p.accept_min_trades}": rs.get("n", 0) >= p.accept_min_trades,
    }
    checks = {k: bool(v) for k, v in checks.items()}
    checks["v1 成立"] = all(checks.values())
    return checks


def is_fragile(base: float, variants) -> bool:
    """I-16：任一扰动使期望 R 变号，或（基准为正时）保留不到基准的一半 → 脆弱。只报告，不阻断冻结样本外。"""
    v = np.asarray(list(variants), float)
    return bool(((v > 0) != (base > 0)).any() or (base > 0 and (v < 0.5 * base).any()))
