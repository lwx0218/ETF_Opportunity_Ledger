# -*- coding: utf-8 -*-
"""刻画补充（etf-dividend-bet-plan-v0 §10 的部分数字来源）：下轨事件按起始月份聚类、Kelly 估计、红利 2017 年起的上轨分桶。
依赖 characterize.py（同目录）与 data/z2_events_all.csv。原为 2026-09-17 会话内一次性脚本，2026-09-25 原样留存为文件，逻辑未改。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np
from characterize import *

ev = pd.read_csv(f"{ROOT_S}/data/z2_events_all.csv")
evl = []
for c, (n, g) in {**{"510880": ("红利ETF", zscore(monthly("510880")))}, **{c: (n, zscore(monthly(c))) for c, n in ETFS.items()}, **{c: (n, zscore(monthly(c))) for c, n in IDX.items()}}.items():
    for e in episodes(g, 2.0, -1): e["code"] = c; e["name"] = n; evl.append(e)
evl = pd.DataFrame(evl).dropna(subset=["f3"])
print("下侧事件", len(evl), "个；不同的起始月份", evl.start.nunique())
cl = evl.groupby("start").agg(n=("code", "size"), f3=("f3", "median"), f6=("f6", "median"), fmin6=("fmin6", "median")).sort_index()
print(cl.to_string())
print("按月份聚合：3月中位", f"{cl.f3.median():+.1%}", ">0 占", f"{(cl.f3>0).mean():.0%}", "6月中位", f"{cl.f6.median():+.1%}")
allp = pd.concat([zscore(monthly(c)) for c in list(ETFS) + ["510880"] + list(IDX)]).dropna(subset=["z", "f3"])
lo = allp[allp.z <= -2]; mu, sd = lo.f3.mean(), lo.f3.std()
print(f"z≤−2：3月均值 {mu:+.1%}，标准差 {sd:.1%}，Kelly f*=μ/σ² = {mu/sd**2:.2f}，胜率 {(lo.f3>0).mean():.0%}，平均盈 {lo.f3[lo.f3>0].mean():+.1%}，平均亏 {lo.f3[lo.f3<=0].mean():+.1%}")
hi = allp[allp.z >= 2]; print(f"z≥2：3月均值 {hi.f3.mean():+.1%}，标准差 {hi.f3.std():.1%}，胜率 {(hi.f3>0).mean():.0%}")
hl = zscore(monthly("510880")); h = hl[(hl.m >= "2017-01")].dropna(subset=["f3"])
s = h[(h.z >= 2) & (h.z < 3)]; print(f"红利 2017 起 z∈[2,3)：n={len(s)} 3月中位 {s.f3.median():+.1%} >0 {(s.f3>0).mean():.0%} 6月内最低中位 {s.fmin6.median():+.1%}")
s = h[h.z >= 2]; print(f"红利 2017 起 z≥2：n={len(s)} 3月中位 {s.f3.median():+.1%} 均值 {s.f3.mean():+.1%} >0 {(s.f3>0).mean():.0%}")
print(f"红利 2017 起 无条件 3月中位 {h.f3.median():+.1%} 均值 {h.f3.mean():+.1%}")
print("上侧事件 f6 分位数：", ev.f6.quantile([.1, .25, .5, .75, .9]).round(3).to_dict())
