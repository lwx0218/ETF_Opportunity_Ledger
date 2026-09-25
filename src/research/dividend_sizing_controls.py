# -*- coding: utf-8 -*-
"""无信号的仓位对照（etf-dividend-enhancement-prereg §6.5 的数字来源）：恒定比例、波动率目标、逆向分批，对红利 ETF 持有不动。
依赖 enh_engine.py（同目录）。原为 2026-09-17 会话内一次性脚本，2026-09-25 原样留存为文件，逻辑未改。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np
from enh_engine import load, COST

d, me = load()
c = d.close; r = c / c.shift(1) - 1
def stats(w, start, end, cash=0.0):
    w = w.shift(1).fillna(1.0)
    ret = w * r + (1 - w) * cash / 245 - (w - w.shift(1)).abs().fillna(0) * COST
    m = (d.date >= start) & (d.date <= end)
    eq = (1 + ret[m]).cumprod(); eb = (1 + r[m]).cumprod()
    dd = lambda e: float((e / e.cummax() - 1).min()); g = lambda e: float(e.iloc[-1] ** (245 / len(e)) - 1)
    return dict(excess=float(eq.iloc[-1] / eb.iloc[-1] - 1), cagr=g(eq), cagr_bh=g(eb), mdd=dd(eq), mdd_bh=dd(eb), avg_w=float(w[m].mean()))
def show(name, w, cash=0.0):
    for lab, (a, b) in {"样本内 07–16": ("2007-01-18", "2016-12-31"), "样本外 17–26": ("2017-01-01", "2026-09-15")}.items():
        s = stats(w, a, b, cash)
        print(f"{name:28s} {lab}：超额 {s['excess']:+.1%} · 年化 {s['cagr']:+.1%} vs 持有 {s['cagr_bh']:+.1%} · 回撤 {s['mdd']:+.0%} vs {s['mdd_bh']:+.0%} · 平均仓位 {s['avg_w']:.0%}")
mend = d.groupby("m").tail(1).index
show("恒定 80/20 每日再平衡", pd.Series(0.8, index=d.index))
vol = r.rolling(63).std() * np.sqrt(245)
target = float(r.loc[d.date <= "2016-12-31"].std() * np.sqrt(245)) * 2 / 3   # 目标只用样本内波动定
wv = (target / vol).clip(upper=1.0).fillna(1.0)
wv_m = pd.Series(np.nan, index=d.index); wv_m.loc[mend] = wv.loc[mend]; wv_m = wv_m.ffill().fillna(1.0)
print(f"波动率目标 = {target:.1%}（样本内持有不动波动的 2/3）")
show("波动率目标（月末调仓）", wv_m); show("波动率目标 · 现金 2%", wv_m, cash=0.02)
peak = c.cummax(); ddn = c / peak - 1
wc = pd.Series(np.where(ddn < -0.30, 1.0, np.where(ddn < -0.20, 0.8, np.where(ddn < -0.10, 0.7, 0.6))), index=d.index)
wc_m = pd.Series(np.nan, index=d.index); wc_m.loc[mend] = wc.loc[mend]; wc_m = wc_m.ffill().fillna(0.6)
show("逆向分批 60→100（按回撤深度）", wc_m); show("逆向分批 · 现金 2%", wc_m, cash=0.02)
show("恒定 60/40（逆向分批的对照）", pd.Series(0.6, index=d.index))
