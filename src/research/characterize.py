# -*- coding: utf-8 -*-
"""刻画（方案 v0 §7）：只做描述，不做交易。所有月份都是样本，不按结果选。
z_t = (当月末收盘 − 之前 20 个已完成月末收盘均值) / 其标准差。前向收益 = 之后 1/3/6 个月。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np, json, os
os.makedirs(f"{ROOT_S}/outputs/research", exist_ok=True)
D = f"{ROOT_S}/data/"
M = D + "monthly/"
ETFS = {"159509": "纳指科技", "159516": "半导体设备", "159819": "AI", "159825": "农业", "501018": "原油LOF", "501225": "全球半导体LOF", "510300": "沪深300",
        "512400": "有色", "512760": "芯片", "512800": "银行", "513100": "纳指100", "515220": "煤炭", "515880": "通信", "518880": "黄金", "588000": "科创50"}
IDX = {"000001": "上证指数", "000905": "中证500", "000016": "上证50", "000015": "上证红利指数", "399001": "深证成指", "hs300": "沪深300指数", "chinext": "创业板指"}

def monthly(code):
    if code == "510880":   # 红利用自己的后复权月末收盘（腾讯 qfq 在 2008 年为负，不能用）
        d = pd.read_csv(D + "kline_hfq_510880.csv", parse_dates=["date"]); d["m"] = d.date.dt.to_period("M")
        g = d.groupby("m").agg(date=("date", "last"), close=("close", "last"), high=("high", "max"), vol=("volume", "sum")).reset_index()
    else:
        g = pd.read_csv(M + f"{code}_month.csv"); g["m"] = pd.PeriodIndex(g.month, freq="M"); g["date"] = pd.to_datetime(g.date)
    g = g[g.m <= "2026-09"].reset_index(drop=True)
    return g[["m", "date", "close", "high", "vol"]]

def zscore(g, n=20):
    c = g.close
    mu = c.shift(1).rolling(n).mean(); sd = c.shift(1).rolling(n).std()
    g = g.copy(); g["z"] = (c - mu) / sd; g["z_high"] = (g.high - mu) / sd
    for k in (1, 3, 6): g[f"f{k}"] = c.shift(-k) / c - 1
    g["fmax6"] = pd.concat([c.shift(-k) for k in range(1, 7)], axis=1).max(axis=1) / c - 1     # 之后 6 个月内最高月末收盘
    g["fmin6"] = pd.concat([c.shift(-k) for k in range(1, 7)], axis=1).min(axis=1) / c - 1
    g["vol_ratio"] = g.vol / g.vol.shift(1).rolling(12).mean()
    return g

BINS = [(-99, -2, "z ≤ −2"), (-2, -1, "−2 < z ≤ −1"), (-1, 1, "−1 < z < 1"), (1, 2, "1 ≤ z < 2"), (2, 3, "2 ≤ z < 3"), (3, 99, "z ≥ 3")]
def table(df, label):
    df = df.dropna(subset=["z", "f3"])
    rows = [f"**{label}** · 月样本 {len(df)} · 无条件：1月中位 {df.f1.median():+.1%} · 3月中位 {df.f3.median():+.1%}（均值 {df.f3.mean():+.1%}，>0 占 {(df.f3>0).mean():.0%}）· 6月中位 {df.f6.median():+.1%}",
            "| z 区间 | n | 1月中位 | 3月中位 | 3月均值 | 3月>0 | 6月中位 | 6月内最高(中位) | 6月内最低(中位) |", "|---|---|---|---|---|---|---|---|---|"]
    for lo, hi, name in BINS:
        s = df[(df.z > lo) & (df.z <= hi)] if lo == -99 else df[(df.z >= lo) & (df.z < hi)]
        if len(s) == 0: rows.append(f"| {name} | 0 | | | | | | | |"); continue
        rows.append(f"| {name} | {len(s)} | {s.f1.median():+.1%} | {s.f3.median():+.1%} | {s.f3.mean():+.1%} | {(s.f3>0).mean():.0%} | {s.f6.median():+.1%} | {s.fmax6.median():+.1%} | {s.fmin6.median():+.1%} |")
    return "\n".join(rows)

def episodes(g, thr=2.0, side=+1):
    """首次穿越 thr 的事件；同一事件持续到 z 回到 thr 以下（上侧）为止。"""
    z = g.z.values; out = []; i = 0
    while i < len(z):
        cond = (z[i] >= thr) if side > 0 else (z[i] <= -thr)
        if not np.isnan(z[i]) and cond:
            j = i
            while j + 1 < len(z) and (not np.isnan(z[j+1])) and ((z[j+1] >= thr) if side > 0 else (z[j+1] <= -thr)): j += 1
            r = g.iloc[i]
            out.append(dict(start=str(g.m.iloc[i]), end=str(g.m.iloc[j]), dur=j - i + 1, z=float(z[i]), f3=float(r.f3), f6=float(r.f6), fmax6=float(r.fmax6), fmin6=float(r.fmin6), vol_ratio=float(r.vol_ratio) if not np.isnan(r.vol_ratio) else None))
            i = j + 1
        else: i += 1
    return out

if __name__ == "__main__":
    out = ["# 刻画 · 方案 v0 §7 · 2026-09-17\n", "> 只做描述。z 用之前 20 个已完成月末收盘的均值和标准差，当月末收盘与之比。前向收益用月末收盘。2026-09 为月中，不计前向。\n"]
    series = {}
    for code, name in {**{"510880": "红利ETF"}, **ETFS}.items(): series[code] = (name, zscore(monthly(code)))
    idx = {code: (name, zscore(monthly(code))) for code, name in IDX.items()}
    # ---- 1. 红利自己 ----
    hl = series["510880"][1]
    out.append("## 1. 红利 ETF 自己\n"); out.append(table(hl, "红利 ETF 510880（2007→，后复权）")); out.append("")
    ep = episodes(hl, 2.0, +1); epl = episodes(hl, 2.0, -1)
    # 利差、大盘 z、量比 对照
    y = pd.read_csv(D + "cgb10y_monthly_oecd.csv"); y["m"] = pd.PeriodIndex(y.period, freq="M")
    div = pd.read_csv(D + "dividends_510880.csv", parse_dates=["date"]); div["m"] = div.date.dt.to_period("M")
    raw = pd.read_csv(D + "kline_hfq_510880.csv", parse_dates=["date"]); raw["m"] = raw.date.dt.to_period("M"); rawm = raw.groupby("m").raw_close.last()
    last_div = pd.Series(np.nan, index=rawm.index)
    for _, r in div.iterrows(): last_div.loc[r.m:] = r["div"]
    dy = (last_div / rawm * 100); spread = dy - y.set_index("m")["yield"].reindex(dy.index)
    hs = idx["hs300"][1].set_index("m").z
    out.append(f"### 1.1 红利 z ≥ 2 的事件（共 {len(ep)} 次）\n")
    out.append("| 开始 | 持续(月) | 进入时 z | 之后3月 | 之后6月 | 6月内最高 | 6月内最低 | 量比 | 沪深300 z | 股息率 | 利差 |"); out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for e in ep:
        m = pd.Period(e["start"], "M")
        sp = spread.get(m, np.nan); d_ = dy.get(m, np.nan); hz = hs.get(m, np.nan)
        out.append(f"| {e['start']} | {e['dur']} | {e['z']:.1f} | {e['f3']:+.1%} | {e['f6']:+.1%} | {e['fmax6']:+.1%} | {e['fmin6']:+.1%} | {e['vol_ratio'] if e['vol_ratio'] is None else round(e['vol_ratio'],1)} | {hz:+.1f} | {'' if np.isnan(d_) else f'{d_:.1f}%'} | {'' if np.isnan(sp) else f'{sp:+.1f}'} |")
    out.append(f"\n### 1.2 红利 z ≤ −2 的事件（共 {len(epl)} 次）\n")
    out.append("| 开始 | 持续(月) | 进入时 z | 之后3月 | 之后6月 | 6月内最高 | 6月内最低 | 量比 | 沪深300 z | 股息率 | 利差 |"); out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for e in epl:
        m = pd.Period(e["start"], "M"); sp = spread.get(m, np.nan); d_ = dy.get(m, np.nan); hz = hs.get(m, np.nan)
        out.append(f"| {e['start']} | {e['dur']} | {e['z']:.1f} | {e['f3']:+.1%} | {e['f6']:+.1%} | {e['fmax6']:+.1%} | {e['fmin6']:+.1%} | {e['vol_ratio'] if e['vol_ratio'] is None else round(e['vol_ratio'],1)} | {hz:+.1f} | {'' if np.isnan(d_) else f'{d_:.1f}%'} | {'' if np.isnan(sp) else f'{sp:+.1f}'} |")
    # 红利 z 全序列（给她对月 K）
    hl.assign(m=hl.m.astype(str))[["m", "close", "z", "z_high", "f3", "f6"]].round(3).to_csv(D + "hl_z_series.csv", index=False)
    # ---- 2. 横截面 ----
    pool = pd.concat([g.assign(code=c, name=n) for c, (n, g) in series.items() if c != "510880"])
    out.append("\n## 2. 横截面 · 15 个容器 ETF（不含红利、不含现金）\n"); out.append(table(pool, "15 个容器 ETF 合并")); out.append("")
    ipool = pd.concat([g.assign(code=c, name=n) for c, (n, g) in idx.items()])
    out.append("## 3. 补充横截面 · 7 个宽基指数（2005→，价格指数，只为样本量）\n"); out.append(table(ipool, "7 个指数合并")); out.append("")
    allp = pd.concat([pool, ipool, hl.assign(code="510880", name="红利ETF")])
    out.append("## 4. 全部合并（红利 + 15 ETF + 7 指数）\n"); out.append(table(allp, "全部合并")); out.append("")
    # 稳健性：12 月窗口、阈值 2.5
    out.append("## 5. 稳健性（只看结论是否脆弱）\n")
    for n_, lab in ((12, "窗口 12 月"), (20, "窗口 20 月")):
        s2 = pd.concat([zscore(monthly(c), n_).assign(code=c) for c in list(ETFS) + ["510880"]] + [zscore(monthly(c), n_).assign(code=c) for c in IDX])
        s2 = s2.dropna(subset=["z", "f3"]); u = s2.f3.median()
        hi2 = s2[s2.z >= 2]; hi25 = s2[s2.z >= 2.5]; lo2 = s2[s2.z <= -2]
        out.append(f"- {lab}：无条件 3 月中位 {u:+.1%}；z ≥ 2（n={len(hi2)}）{hi2.f3.median():+.1%}；z ≥ 2.5（n={len(hi25)}）{hi25.f3.median():+.1%}；z ≤ −2（n={len(lo2)}）{lo2.f3.median():+.1%}")
    # 事件视角（首次触及）：全部合并
    out.append("\n## 6. 事件视角（首次触及 z ≥ 2 起算，同一段只记一次）\n")
    ev = []
    for c, (n, g) in {**series, **idx}.items():
        for e in episodes(g, 2.0, +1): e["code"] = c; e["name"] = n; ev.append(e)
    ev = pd.DataFrame(ev).dropna(subset=["f3"])
    out.append(f"全部：事件 {len(ev)} 次 · 持续中位 {ev.dur.median():.0f} 月 · 持续 ≥ 3 月的占 {(ev.dur>=3).mean():.0%} · 进入后 3 月中位 {ev.f3.median():+.1%}（>0 占 {(ev.f3>0).mean():.0%}）· 6 月中位 {ev.f6.median():+.1%} · 6 月内最高中位 {ev.fmax6.median():+.1%} · 6 月内最低中位 {ev.fmin6.median():+.1%}")
    ride = ev[ev.dur >= 3]; rev = ev[ev.dur < 3]
    out.append(f"沿轨走（持续 ≥ 3 月，n={len(ride)}）：进入时 z 中位 {ride.z.median():.1f} · 量比中位 {ride.vol_ratio.median():.1f} · 之后 6 月中位 {ride.f6.median():+.1%}")
    out.append(f"很快回落（持续 < 3 月，n={len(rev)}）：进入时 z 中位 {rev.z.median():.1f} · 量比中位 {rev.vol_ratio.median():.1f} · 之后 6 月中位 {rev.f6.median():+.1%}")
    ev.to_csv(D + "z2_events_all.csv", index=False)
    evl = []
    for c, (n, g) in {**series, **idx}.items():
        for e in episodes(g, 2.0, -1): e["code"] = c; e["name"] = n; evl.append(e)
    evl = pd.DataFrame(evl).dropna(subset=["f3"])
    out.append(f"\n下侧 z ≤ −2 事件 {len(evl)} 次 · 持续中位 {evl.dur.median():.0f} 月 · 进入后 3 月中位 {evl.f3.median():+.1%}（>0 占 {(evl.f3>0).mean():.0%}）· 6 月中位 {evl.f6.median():+.1%} · 6 月内最低中位 {evl.fmin6.median():+.1%}")
    # ---- 7. 当前状态 ----
    out.append("\n## 7. 当前（2026-09-16 月中价对带）\n"); out.append("| 容器 | 当前 z | 月内最高 z | 12 月已实现波动(年化) |"); out.append("|---|---|---|---|")
    for c, (n, g) in {**series, **idx}.items():
        r = g.iloc[-1]; vol12 = float(g.close.pct_change().iloc[-13:-1].std() * np.sqrt(12))
        out.append(f"| {n} {c} | {r.z:+.1f} | {r.z_high:+.1f} | {vol12:.0%} |")
    # ---- 8. 验收对照（方案 §6 第一条） ----
    u = allp.dropna(subset=["z", "f3"]); um = u.f3.median()
    hi = u[u.z >= 2]; lo = u[u.z <= -2]
    c1 = (hi.f3.median() <= um - 0.02) and len(hi) >= 100; c2 = lo.f3.median() >= um + 0.02
    out.append(f"\n## 8. 对照方案 §6 的刻画通过条件\n\n- 上侧：z ≥ 2 之后 3 月中位 {hi.f3.median():+.1%} vs 无条件 {um:+.1%}，差 {hi.f3.median()-um:+.1%}，n={len(hi)} → {'满足' if c1 else '不满足'}（要求 ≤ −2 个百分点且 n ≥ 100）")
    out.append(f"- 下侧：z ≤ −2 之后 3 月中位 {lo.f3.median():+.1%} vs 无条件 {um:+.1%}，差 {lo.f3.median()-um:+.1%}，n={len(lo)} → {'满足' if c2 else '不满足'}（要求 ≥ +2 个百分点）")
    open(f"{ROOT_S}/outputs/research/characterization.md", "w", encoding="utf-8").write("\n".join(out)); print("\n".join(out))
