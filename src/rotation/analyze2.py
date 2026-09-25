"""轮动面板 · 第二步：读 data/panel_daily.csv → 周度回放 data/weekly_replay.csv 与面板数据 data/panel.json。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np, json
P = pd.read_csv(f"{ROOT_S}/data/panel_daily.csv", parse_dates=["date"])
P = P[P.date >= "2026-01-01"].copy()
dates = sorted(P.date.unique())
W = P.pivot(index="date", columns="container", values="close")
bench = W["宽基-沪深300"]

# ---------- 1. 事件日前向收益 ----------
EP = [("E1","2026-03-02","原油",["半导体","宽基-科创50"]),("E2","2026-05-11","Q-全球半导体",[]),("E3","2026-06-01","Q-全球半导体",[]),
      ("E4","2026-08-31","农业",["半导体","AI算力"]),("E5","2026-09-10","银行",["半导体","AI算力"])]
def fwd(series, i, n):
    j = min(i+n, len(series)-1); return series.iloc[j]/series.iloc[i]-1, (j-i)
out = []
for eid, d, dest, srcs in EP:
    d = pd.Timestamp(d); i0 = dates.index(d); i5 = i0-5
    for tag, i in (("t-5", i5), ("t", i0)):
        row = {"ep": eid, "from": tag, "date": str(dates[i].date())}
        for n in (5, 10, 20):
            r, got = fwd(W[dest], i, n); b, _ = fwd(bench, i, n)
            row[f"dest_{n}d"] = r; row[f"bench_{n}d"] = b; row[f"got_{n}"] = got
            if srcs:
                row[f"src_{n}d"] = float(np.mean([fwd(W[s], i, n)[0] for s in srcs]))
        out.append(row)
F = pd.DataFrame(out)
pd.set_option("display.width", 220)
print(F.to_string(index=False, float_format=lambda x: f"{x:+.1%}" if abs(x) < 5 else f"{x:.0f}"))

# ---------- 2. 周度回放 ----------
P["week"] = P.date.dt.to_period("W-FRI")
fridays = P.groupby("week").date.max().tolist()          # 每周最后一个交易日
res = []
for k in range(len(fridays)-1):
    d, dn = fridays[k], fridays[k+1]
    s = P[P.date==d].set_index("container")
    nxt = P[P.date==dn].set_index("container")["close"]
    wk = (nxt/s["close"]-1).dropna()
    top = s.sort_values("rank_1m").index[:3]
    filt = s[(s.prem.fillna(0) < 0.2) & (~s.kell.isin(["EXH","DROP"]))].sort_values("rank_1m").index[:3]
    bot = s.sort_values("rank_1m").index[-3:]
    res.append({"date": d, "next": dn, "top3": wk[top].mean(), "top3_filt": wk[filt].mean(), "bot3": wk[bot].mean(),
                "ew": wk.mean(), "hs300": wk["宽基-沪深300"], "top3_names": "/".join(top), "filt_names": "/".join(filt)})
R = pd.DataFrame(res)
def comp(x): return (1+x).prod()-1
print("\n周数", len(R), "| 累计: top3 %+.1f%% | top3_filt %+.1f%% | bot3 %+.1f%% | 等权 %+.1f%% | 沪深300 %+.1f%%" % tuple(100*comp(R[c]) for c in ["top3","top3_filt","bot3","ew","hs300"]))
print("胜率(周跑赢等权): top3 %.0f%% | top3_filt %.0f%% | bot3 %.0f%%" % tuple(100*(R[c] > R.ew).mean() for c in ["top3","top3_filt","bot3"]))
print("周均超额(vs等权): top3 %+.2f%% | top3_filt %+.2f%% | bot3 %+.2f%%" % tuple(100*(R[c]-R.ew).mean() for c in ["top3","top3_filt","bot3"]))
R.to_csv(f"{ROOT_S}/data/weekly_replay.csv", index=False)
print(R[["date","top3_names","top3","ew"]].tail(8).to_string(index=False, float_format=lambda x: f"{x:+.1%}"))

# ---------- 3. 面板 JSON（周五截面） ----------
cont_order = ["宽基-沪深300","宽基-科创50","半导体","半导体设备","AI算力","通信","有色","煤炭","黄金","原油","农业","红利","银行","现金","Q-全球半导体","Q-纳指科技","Q-纳指100"]
panel = {"weeks": [str(d.date()) for d in fridays], "containers": cont_order, "cells": {}}
for c in cont_order:
    cells = []
    for d in fridays:
        r = P[(P.date==d)&(P.container==c)]
        if not len(r):  # 停牌等缺日：取 5 日内最近一行
            r = P[(P.container==c)&(P.date<d)&(P.date>=d-pd.Timedelta(days=5))].sort_values("date")
        if not len(r): cells.append(None); continue
        r = r.iloc[-1]
        cells.append({"rank": int(r.rank_1m), "rs": round(float(r.rs_1m),4), "rs1w": round(float(r.rs_1w),4), "kell": r.kell, "ext": round(float(r.ext),2),
                      "v20": None if pd.isna(r.vol_20_250) else round(float(r.vol_20_250),2), "v5": None if pd.isna(r.vol_5_60) else round(float(r.vol_5_60),2),
                      "prem": None if pd.isna(r.prem) else round(float(r.prem),4), "close": float(r.close)})
    panel["cells"][c] = cells
# 事件日截面（t-5 与 t 全表）
EPD = [("E1","2026-03-02","原油","霍尔木兹受阻，布伦特开盘 +13%，原油 LOF 溢价 >26%",["半导体","宽基-科创50"]),
       ("E2","2026-05-11","Q-全球半导体","全球芯片 LOF 溢价 46–47%，上交所重点监控",[]),
       ("E3","2026-06-01","Q-全球半导体","全球芯片LOF / 纳指科技ETF / 中韩半导体ETF 同日临停",[]),
       ("E4","2026-08-31","农业","粮食 ETF +6.3%，AI 核心标的低迷，半导体 ETF 净流出",["半导体","AI算力","宽基-科创50"]),
       ("E5","2026-09-10","银行","银行主题 ETF 全线涨，粮食/农产品全线跌，成交连续 4 日 <2 万亿",["半导体","AI算力","宽基-科创50"])]
panel["episodes"] = []
for eid, d, dest, why, srcs in EPD:
    d = pd.Timestamp(d); i0 = dates.index(d); d5 = dates[i0-5]
    ep = {"id": eid, "date": str(d.date()), "t5": str(d5.date()), "dest": dest, "why": why, "sources": srcs, "tables": {}}
    for tag, dd in (("t5", d5), ("t", d)):
        s = P[P.date==dd].sort_values("rank_1m")
        ep["tables"][tag] = [{"c": r.container, "rank": int(r.rank_1m), "rs": round(float(r.rs_1m),3), "v20": None if pd.isna(r.vol_20_250) else round(float(r.vol_20_250),2),
                              "v5": None if pd.isna(r.vol_5_60) else round(float(r.vol_5_60),2), "prem": None if pd.isna(r.prem) else round(float(r.prem),3), "ext": round(float(r.ext),2), "kell": r.kell} for _, r in s.iterrows()]
    # 源头/目的地 t-10..t 状态序列
    seqs = {}
    for c in srcs + [dest]:
        q = P[(P.container==c)&(P.date>=dates[i0-10])&(P.date<=d)].sort_values("date")
        seqs[c] = {"kell": q.kell.tolist(), "rank": [int(x) for x in q.rank_1m], "prem": [None if pd.isna(x) else round(float(x),3) for x in q.prem], "dates": [str(x.date()) for x in q.date]}
    ep["seqs"] = seqs
    f5 = F[(F.ep==eid)&(F["from"]=="t-5")].iloc[0]
    ep["fwd"] = {k: (None if pd.isna(f5[k]) else round(float(f5[k]),4)) for k in ["dest_5d","dest_10d","dest_20d","bench_5d","bench_10d","bench_20d","src_5d","src_10d","src_20d"] if k in f5}
    ep["fwd_got"] = {k: int(f5[k]) for k in ["got_5","got_10","got_20"]}
    panel["episodes"].append(ep)
panel["replay"] = {"weeks": len(R), "cum": {c: round(float(comp(R[c])),4) for c in ["top3","top3_filt","bot3","ew","hs300"]},
                   "hit": {c: round(float((R[c] > R.ew).mean()),3) for c in ["top3","top3_filt","bot3"]},
                   "rows": [{"date": str(r.date.date()), "top3": r.top3_names, "r_top3": round(float(r.top3),4), "r_ew": round(float(r.ew),4), "r_hs": round(float(r.hs300),4)} for _, r in R.iterrows()]}
json.dump(panel, open(f"{ROOT_S}/data/panel.json","w"), ensure_ascii=False)
print("\npanel.json weeks", len(fridays), "first", fridays[0].date(), "last", fridays[-1].date())
