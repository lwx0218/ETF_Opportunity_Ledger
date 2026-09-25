# -*- coding: utf-8 -*-
"""宇宙层面的描述（etf-rotation-prereg-v1 §1.1 的数字来源）：不是 v1 信号的回测，形态状态 / 止损 / 移动止盈一概未测。
读 data/monthly/*_month.csv（剔除 510880：腾讯 qfq 在 2008 年为负价，红利由 000015 代表），2012-06 → 2026-08：
A · 每月上涨容器占比、最差月份当月最好的容器；B · 完美后视 vs 朴素动量 vs 等权 vs 沪深300；C · 只留 A 股权益容器时的同一统计。
原为 2026-09-19 会话内一次性脚本，2026-09-25 原样留存为文件，逻辑未改。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np, glob, os

M = f"{ROOT_S}/data/monthly/"
NONA = {"518880", "501018", "513100", "159509", "501225"}   # 黄金 / 原油 / 纳指 / 纳指科技 / 全球半导体

def load_px():
    ser = {}
    for f in sorted(glob.glob(M + "*_month.csv")):
        c = os.path.basename(f).replace("_month.csv", "")
        if c == "510880": continue
        d = pd.read_csv(f); d["m"] = pd.PeriodIndex(d.month, freq="M"); s = d.set_index("m").close
        if (s <= 0).any(): continue
        ser[c] = s
    px = pd.DataFrame(ser).sort_index()
    return px[px.index <= "2026-08"]                       # 2026-09 为月中，剔除

def stats(x, label):
    x = x.dropna(); eq = (1 + x).cumprod()
    mdd = float((eq / eq.cummax() - 1).min()); cagr = float(eq.iloc[-1] ** (12 / len(x)) - 1)
    print(f"  {label:34s} 年化 {cagr:+7.1%} · 最大回撤 {mdd:+6.0%} · 月胜率 {(x>0).mean():.0%}")

def mom(px, r, k, look=1):
    sig = px.pct_change(look).shift(1)                      # 上月末已知
    out = []
    for m in r.index:
        s = sig.loc[m].dropna(); s = s[r.loc[m].notna().reindex(s.index).fillna(False)]
        out.append(r.loc[m, s.nlargest(k).index].mean() if len(s) >= k else np.nan)
    return pd.Series(out, index=r.index)

if __name__ == "__main__":
    px = load_px()
    # ---- A ----
    r = px.pct_change(); n = r.notna().sum(axis=1); r = r[n >= 8]; n = n[n >= 8]
    up = (r > 0).sum(axis=1); frac = up / n
    print(f"A · 样本 {r.index[0]} → {r.index[-1]}，{len(r)} 个月，容器数 {n.min()}–{n.max()}（中位 {int(n.median())}）")
    print("  上涨占比 中位 %.0f%% · 25/75 分位 %.0f%%/%.0f%% · 最低 %.0f%% · 最高 %.0f%%" % (frac.median()*100, frac.quantile(.25)*100, frac.quantile(.75)*100, frac.min()*100, frac.max()*100))
    print("  一个都没涨：%d 个月（%.0f%%）· 涨不到 20%%：%d 个月（%.0f%%）" % ((up==0).sum(), (up==0).mean()*100, (frac<0.2).sum(), (frac<0.2).mean()*100))
    print("  一个都没涨的月份：", [str(x) for x in frac[up == 0].index])
    ew = r.mean(axis=1); w = ew.nsmallest(12).index
    t = pd.DataFrame({"等权": ew[w], "当月最好": r.loc[w].max(axis=1), "最好的是谁": r.loc[w].idxmax(axis=1), "上涨占比": frac[w], "容器数": n[w]}).sort_index()
    print(t.assign(**{"等权": lambda x: (x["等权"]*100).round(1), "当月最好": lambda x: (x["当月最好"]*100).round(1), "上涨占比": lambda x: (x["上涨占比"]*100).round(0)}).to_string())
    # ---- B ----
    print("\nB · 存在性（完美后视）")
    stats(r.max(axis=1), "完美后视 · 每月最好的 1 个"); stats(r.apply(lambda row: row.nlargest(3).mean(), axis=1), "完美后视 · 每月最好的 3 个")
    print("  可捕获性（用上个月的信息去挑）")
    stats(mom(px, r, 1, 1), "近 1 月动量 · 前 1"); stats(mom(px, r, 3, 1), "近 1 月动量 · 前 3")
    stats(mom(px, r, 1, 3), "近 3 月动量 · 前 1"); stats(mom(px, r, 3, 3), "近 3 月动量 · 前 3")
    print("  对照"); stats(r.mean(axis=1), "全容器等权"); stats(r["hs300"], "沪深300")
    cc = r.corr().values; mk = ~np.eye(len(cc), dtype=bool); print(f"  月度收益平均两两相关：全样本 {np.nanmean(cc[mk]):.2f}")
    for lab, sub in (("等权跌超 3% 的月份", r[r.mean(axis=1) < -0.03]), ("等权涨超 3% 的月份", r[r.mean(axis=1) > 0.03])):
        c = sub.corr().values; m2 = ~np.eye(len(c), dtype=bool); print(f"  {lab}（n={len(sub)}）{np.nanmean(c[m2]):.2f}")
    # ---- C ----
    print("\nC · 全部容器 vs 只留 A 股权益容器（容器数 ≥ 6 的月份）")
    for lab, cols in (("全部容器", list(px.columns)), ("只留 A 股权益容器", [c for c in px.columns if c not in NONA])):
        rr = px[cols].pct_change(); nn = rr.notna().sum(axis=1); rr = rr[nn >= 6]; nn = nn[nn >= 6]
        uu = (rr > 0).sum(axis=1); ff = uu / nn
        print(f"  {lab}（{len(cols)} 个，{len(rr)} 个月）：一个都没涨 {(uu==0).sum()} 个月（{(uu==0).mean():.0%}）· 涨不到 20% 的 {(ff<0.2).mean():.0%} · 上涨占比中位 {ff.median():.0%}")
        ww = rr.mean(axis=1).nsmallest(8).index
        print("    最差 8 个月当月最好的容器：", " ".join(f"{str(m)}:{rr.loc[m].max():+.0%}({rr.loc[m].idxmax()})" for m in sorted(ww)))
    mo = mom(px, r, 1, 1).dropna(); eq = (1 + mo).cumprod(); dd = eq / eq.cummax() - 1
    print(f"  近 1 月动量·前 1 的回撤：最深 {dd.min():.0%}，谷底在 {dd.idxmin()}；深于 30% 的区间 {dd[dd<-0.3].index[0]} → {dd[dd<-0.3].index[-1]}")
    print("  2015-06 → 2016-02 逐月：", " ".join(f"{str(m)}:{mo[m]:+.0%}" for m in mo.index if "2015-06" <= str(m) <= "2016-02"))
