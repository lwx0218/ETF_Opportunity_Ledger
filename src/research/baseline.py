# -*- coding: utf-8 -*-
"""单标的增强 · 基线规则卡：持有 + 离场/回场，超额对自身持有不动。
信号用 t 日收盘，t+1 开盘成交；成本每边 0.05%（佣金+滑点）。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np, json, sys, os
os.makedirs(f"{ROOT_S}/outputs/research", exist_ok=True)

COST = 0.0005

def load_510880():
    raw = pd.read_csv(f"{ROOT_S}/data/kline_raw_510880.csv", parse_dates=["date"]).reset_index(drop=True)
    qfq = pd.read_csv(f"{ROOT_S}/data/kline_long_510880.csv", parse_dates=["date"]).reset_index(drop=True)
    off = raw.close - qfq.close
    div = (off.shift(1) - off).clip(lower=0).fillna(0)          # 除息日的每股分红
    # 乘法全收益：因子 f_t，使得 f_t*raw_t 的日收益 = (raw_t + div_t)/raw_{t-1} - 1
    tr = (raw.close + div) / raw.close.shift(1); tr.iloc[0] = 1
    level = tr.cumprod(); f = level / raw.close * raw.close.iloc[0]   # 以首日价格为基
    f = f / f.iloc[-1]                                                  # 锚到最新价（与 qfq 习惯一致）
    d = raw.copy()
    for c in ("open", "close", "high", "low"): d[c] = raw[c] * f
    return d

def load_588000():
    return pd.read_csv(f"{ROOT_S}/data/kline_long_588000.csv", parse_dates=["date"]).reset_index(drop=True)

def indicators(d, p):
    c, h, l, v = d.close, d.high, d.low, d.volume
    d["ema10"] = c.ewm(span=p["ema_fast"], adjust=False).mean(); d["ema20"] = c.ewm(span=p["ema"], adjust=False).mean()
    d["sma50"] = c.rolling(p["sma"]).mean(); d["v20"] = v.rolling(20).mean()
    d["hi_n"] = h.rolling(p["don"]).max().shift(1); d["lo_n"] = l.rolling(p["don"]).min().shift(1)
    return d

def positions(d, rule, p):
    """返回每日目标仓位（0/1），按 t 收盘信号决定 t+1 的仓位。"""
    c = d.close; pos = np.ones(len(d)); inpos = True
    below = (c < d.ema20); above = (c > d.ema20)
    for i in range(1, len(d)):
        if rule == "A_ema":      # 收盘跌破 EMA 出，站上回
            if inpos and below.iloc[i]: inpos = False
            elif not inpos and above.iloc[i]: inpos = True
        elif rule == "B_ema2":   # 连续两日跌破 EMA 出，连续两日站上回
            if inpos and below.iloc[i] and below.iloc[i-1]: inpos = False
            elif not inpos and above.iloc[i] and above.iloc[i-1]: inpos = True
        elif rule == "C_sma":    # 50 日均线滤波
            if inpos and c.iloc[i] < d.sma50.iloc[i]: inpos = False
            elif not inpos and c.iloc[i] > d.sma50.iloc[i]: inpos = True
        elif rule == "D_don":    # N 日新低出，N 日新高回
            if inpos and c.iloc[i] < d.lo_n.iloc[i]: inpos = False
            elif not inpos and c.iloc[i] > d.hi_n.iloc[i]: inpos = True
        elif rule == "E_drop":   # 放量破位出（收盘 < 快慢 EMA 且量 > 1.5×20 日均量）；收盘站上 EMA20 回
            if inpos and c.iloc[i] < d.ema10.iloc[i] and c.iloc[i] < d.ema20.iloc[i] and d.volume.iloc[i] > p["vol"] * d.v20.iloc[i]: inpos = False
            elif not inpos and above.iloc[i]: inpos = True
        pos[i] = 1 if inpos else 0
    return pd.Series(pos, index=d.index)

def run(d, rule, p, start):
    d = indicators(d.copy(), p)
    pos = positions(d, rule, p).shift(1).fillna(1)   # t+1 生效
    # 用开盘价成交：t+1 日仓位变化在 t+1 开盘发生，所以当日收益 = pos_{t+1} * (close_{t+1}/open_{t+1}-1) + pos_t*(open_{t+1}/close_t -1)
    o, c = d.open, d.close
    r_gap = o / c.shift(1) - 1; r_day = c / o - 1
    pos_prev = pos.shift(1).fillna(1)
    ret = pos_prev * r_gap + pos * r_day - (pos != pos_prev).astype(float) * COST
    bh = c / c.shift(1) - 1
    m = d.date >= start
    ret, bh, pos, d = ret[m], bh[m], pos[m], d[m]
    eq, eqb = (1 + ret).cumprod(), (1 + bh).cumprod()
    dd = lambda e: float((e / e.cummax() - 1).min())
    # 离场段：每段 B&H 收益（策略"躲过"的收益，负 = 躲过下跌）
    spells = []; out = False
    for i in range(len(pos)):
        if pos.iloc[i] == 0 and not out: out = True; i0 = i
        elif pos.iloc[i] == 1 and out: out = False; spells.append((d.date.iloc[i0].date(), d.date.iloc[i].date(), float(c.iloc[i] / c.iloc[i0] - 1)))
    if out: spells.append((d.date.iloc[i0].date(), d.date.iloc[-1].date(), float(c.iloc[-1] / c.iloc[i0] - 1)))
    av = np.array([s[2] for s in spells]) if spells else np.array([0.0])
    years = d.date.dt.year
    yearly = {int(y): (float((1 + ret[years == y]).prod() - 1), float((1 + bh[years == y]).prod() - 1)) for y in sorted(years.unique())}
    return dict(rule=rule, total=float(eq.iloc[-1] - 1), bh=float(eqb.iloc[-1] - 1), excess=float(eq.iloc[-1] / eqb.iloc[-1] - 1),
                mdd=dd(eq), mdd_bh=dd(eqb), trades=len(spells), in_mkt=float(pos.mean()), avoided_mean=float(-av.mean()), avoided_med=float(-np.median(av)),
                hit=float((av < 0).mean()), worst_miss=float(av.max()), best_avoid=float(-av.min()), yearly=yearly, spells=spells)

RULES = {"A_ema": "收盘跌破 20 日 EMA 出 · 站上回", "B_ema2": "连续 2 日跌破 20 日 EMA 出 · 连续 2 日站上回", "C_sma": "收盘跌破 50 日均线出 · 站上回",
         "D_don": "20 日新低出 · 20 日新高回", "E_drop": "放量破位出（<10/20 EMA 且量 >1.5×）· 站上 20 EMA 回"}
BASE = dict(ema=20, ema_fast=10, sma=50, don=20, vol=1.5)
PERT = [dict(BASE, ema=16, ema_fast=8, sma=40, don=16, vol=1.2), dict(BASE, ema=24, ema_fast=12, sma=60, don=24, vol=1.8)]

def report(name, d, start):
    out = [f"## {name} · 起点 {start} · 成本每边 0.05% · 信号收盘、次日开盘成交\n"]
    base_bh = None
    rows = []
    for rule, desc in RULES.items():
        r = run(d, rule, BASE, start); base_bh = r["bh"]
        p1, p2 = run(d, rule, PERT[0], start), run(d, rule, PERT[1], start)
        yr = " · ".join(f"{y}: {s:+.0%}/{b:+.0%}" for y, (s, b) in r["yearly"].items())
        rows.append((rule, desc, r, p1, p2, yr))
    out.append(f"持有不动：{base_bh:+.1%}，最大回撤 {rows[0][2]['mdd_bh']:+.0%}\n")
    out.append("| 规则 | 总收益 | 对持有超额 | 最大回撤 | 离场次数 | 在场比例 | 每次离场躲过(均值/中位) | 离场命中率 | 最大踏空 | 参数 −20% / +20% 超额 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for rule, desc, r, p1, p2, yr in rows:
        out.append(f"| {desc} | {r['total']:+.1%} | **{r['excess']:+.1%}** | {r['mdd']:+.0%} | {r['trades']} | {r['in_mkt']:.0%} | {r['avoided_mean']:+.2%} / {r['avoided_med']:+.2%} | {r['hit']:.0%} | {r['worst_miss']:+.1%} | {p1['excess']:+.1%} / {p2['excess']:+.1%} |")
    out.append("\n逐年（策略/持有）：")
    for rule, desc, r, p1, p2, yr in rows: out.append(f"- {desc}：{yr}")
    return "\n".join(out), rows

if __name__ == "__main__":
    md = ["# 单标的增强 · 基线规则卡 · 2026-09-16\n", "> 问题：默认满仓持有一只 ETF，加一条最简单的离场/回场规则，对「买了不动」有没有超额？每条规则一个信号、一个退出。\n"]
    a, ra = report("红利 ETF 510880（含分红的全收益，用不复权价 + 除息日分红乘法复权）", load_510880(), "2020-06-01")
    b, rb = report("科创50 ETF 588000（前复权，无分红）", load_588000(), "2021-03-01")
    md += [a, "", b]
    open(f"{ROOT_S}/outputs/research/baseline_card.md", "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))
    # 离场段明细留档
    json.dump({"510880": {r[0]: [(str(x), str(y), round(z, 4)) for x, y, z in r[2]["spells"]] for r in ra}, "588000": {r[0]: [(str(x), str(y), round(z, 4)) for x, y, z in r[2]["spells"]] for r in rb}},
              open(f"{ROOT_S}/data/baseline_spells.json", "w"), ensure_ascii=False)
