# -*- coding: utf-8 -*-
"""红利 ETF 增强 · 引擎。月末收盘出信号，次一交易日开盘成交，成本每边 0.05%，后复权全收益，对照 = 持有不动。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np

D = f"{ROOT_S}/data/"
COST = 0.0005

def load():
    d = pd.read_csv(D + "kline_hfq_510880.csv", parse_dates=["date"]).reset_index(drop=True)
    d["m"] = d.date.dt.to_period("M")
    hs = pd.read_csv(D + "monthly/hs300_month.csv"); hs["m"] = pd.PeriodIndex(hs.month, freq="M")
    cn = pd.read_csv(D + "monthly/chinext_month.csv"); cn["m"] = pd.PeriodIndex(cn.month, freq="M")
    me = d.groupby("m").agg(date=("date", "last"), close=("close", "last"), high=("high", "max"), low=("low", "min")).reset_index()
    me = me.merge(hs[["m", "close"]].rename(columns={"close": "hs300"}), on="m", how="left")
    me = me.merge(cn[["m", "close"]].rename(columns={"close": "chinext"}), on="m", how="left")
    return d, me

# ---------- 月度信号（每个函数返回 0/1 目标仓位序列，索引 = me.index；信号在该月末收盘已知） ----------
def sig_trend(me, n=10):
    sma = me.close.rolling(n).mean()
    return (me.close > sma).astype(float).where(sma.notna())

def sig_dd(me, x=0.15, y=0.10):
    """回撤规则：从月末收盘历史高点回撤 > x 出；出场后从出场以来最低月末收盘反弹 > y 回。"""
    c = me.close.values; peak = -np.inf; pos = np.ones(len(c)); inpos = True; low = np.inf
    for i in range(len(c)):
        peak = max(peak, c[i])
        if inpos and c[i] / peak - 1 < -x: inpos = False; low = c[i]
        elif not inpos:
            low = min(low, c[i])
            if c[i] / low - 1 > y: inpos = True; peak = c[i]
        pos[i] = 1 if inpos else 0
    return pd.Series(pos, index=me.index)

def sig_mkt_trend(me, n=10):
    sma = me.hs300.rolling(n).mean()
    return (me.hs300 > sma).astype(float).where(sma.notna())

def sig_rs(me, n=6, ref="hs300"):
    """相对强弱：红利 n 月收益 ≥ 参照指数 n 月收益 则持有。"""
    r_self = me.close / me.close.shift(n) - 1; r_ref = me[ref] / me[ref].shift(n) - 1
    return (r_self >= r_ref).astype(float).where(r_self.notna() & r_ref.notna())

# ---------- 回测 ----------
def run(d, me, pos_m, start, end):
    """pos_m：月度目标仓位（该月末收盘决定，下月第一个交易日开盘执行）。"""
    # 把月度仓位映射到日线：在该月最后一个交易日"决定"，下一交易日生效
    decide = pd.Series(pos_m.values, index=me.date.values)
    pos_d = pd.Series(np.nan, index=d.date.values); pos_d.loc[decide.index] = decide.values
    pos_d = pos_d.shift(1).ffill().fillna(1.0)           # 次日生效；起点默认满仓
    pos = pd.Series(pos_d.values, index=d.index)
    o, c = d.open, d.close
    r_gap = o / c.shift(1) - 1; r_day = c / o - 1
    pos_prev = pos.shift(1).fillna(1.0)
    ret = (1 + pos_prev * r_gap) * (1 + pos * r_day) - 1 - (pos != pos_prev).astype(float) * COST   # 复合，不用加法近似
    bh = c / c.shift(1) - 1
    m = (d.date >= start) & (d.date <= end)
    ret, bh, pos, dd_ = ret[m], bh[m], pos[m], d[m]
    eq, eqb = (1 + ret).cumprod(), (1 + bh).cumprod()
    mdd = lambda e: float((e / e.cummax() - 1).min())
    spells = []; out = False
    for i in range(len(pos)):
        if pos.iloc[i] == 0 and not out: out = True; i0 = i
        elif pos.iloc[i] == 1 and out: out = False; spells.append((dd_.date.iloc[i0].date(), dd_.date.iloc[i].date(), float(c[m].iloc[i] / c[m].iloc[i0] - 1)))
    if out: spells.append((dd_.date.iloc[i0].date(), dd_.date.iloc[-1].date(), float(c[m].iloc[-1] / c[m].iloc[i0] - 1)))
    av = np.array([s[2] for s in spells]) if spells else np.array([0.0])
    yrs = dd_.date.dt.year
    yearly = {int(y): float((1 + ret[yrs == y]).prod() / (1 + bh[yrs == y]).prod() - 1) for y in sorted(yrs.unique())}
    n_years = (dd_.date.iloc[-1] - dd_.date.iloc[0]).days / 365.25
    ex_year = lambda Y: float(np.prod([1 + v for y, v in yearly.items() if y != Y]) - 1)
    return dict(total=float(eq.iloc[-1] - 1), bh=float(eqb.iloc[-1] - 1), excess=float(eq.iloc[-1] / eqb.iloc[-1] - 1),
                mdd=mdd(eq), mdd_bh=mdd(eqb), trades_yr=len(spells) / n_years, in_mkt=float(pos.mean()),
                avoided_med=float(-np.median(av)), hit=float((av < 0).mean()) if spells else float("nan"), worst_miss=float(av.max()) if spells else 0.0,
                yearly=yearly, ex_year=ex_year, spells=spells, ret=ret, bh_ret=bh)

def fmt(name, r, ex=None):
    yr = " ".join(f"{y % 100:02d}:{v:+.0%}" for y, v in r["yearly"].items())
    exs = f" · 剔{ex}: {r['ex_year'](ex):+.1%}" if ex else ""
    return (f"| {name} | {r['excess']:+.1%} | {r['mdd']:+.0%} / {r['mdd_bh']:+.0%} | {r['trades_yr']:.1f} | {r['in_mkt']:.0%} | "
            f"{r['avoided_med']:+.1%} | {r['hit']:.0%} | {r['worst_miss']:+.1%} |{exs} {yr}")
