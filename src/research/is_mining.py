# -*- coding: utf-8 -*-
"""样本内 2007-01-18 → 2016-12-31 · 粗网格探索（预注册 §2.1）。只跑这里列出的配置，不加。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
from enh_engine import *
d, me = load()
IS0, IS1 = "2007-01-18", "2016-12-31"
# 信号需要前 N 个月的历史；2007 年前几个月信号为 NaN → 视为持有（默认满仓）
def clean(s): return s.fillna(1.0)
configs = {}
for n in (6, 10, 12): configs[f"A 趋势 {n}m"] = clean(sig_trend(me, n))
for x in (0.10, 0.15, 0.20, 0.25):
    for y in (0.10, 0.20): configs[f"B 回撤 出{int(x*100)}/回{int(y*100)}"] = sig_dd(me, x, y)
for n in (6, 10, 12): configs[f"C1 大盘趋势 {n}m"] = clean(sig_mkt_trend(me, n))
for n in (3, 6): configs[f"C2 相对强弱 {n}m(vs沪深300)"] = clean(sig_rs(me, n, "hs300"))
configs["A10 且 C1_10"] = clean(sig_trend(me, 10)) * clean(sig_mkt_trend(me, 10))
configs["A10 或 C1_10"] = ((clean(sig_trend(me, 10)) + clean(sig_mkt_trend(me, 10))) > 0).astype(float)
configs["A10 且 B15/10"] = clean(sig_trend(me, 10)) * sig_dd(me, 0.15, 0.10)

rows = ["| 规则 | 对持有超额 | 最大回撤 策略/持有 | 每年交易 | 在场 | 每次离场躲过(中位) | 离场命中 | 最大踏空 | 剔 2008 · 逐年超额 |", "|---|---|---|---|---|---|---|---|---|"]
res = {}
for k, s in configs.items():
    r = run(d, me, s, IS0, IS1); res[k] = r
    rows.append(fmt(k, r, ex=2008))
bh = res[list(res)[0]]
print(f"样本内 {IS0}→{IS1} · 持有不动 {bh['bh']:+.1%}，最大回撤 {bh['mdd_bh']:+.0%}\n")
print("\n".join(rows))
import json
json.dump({k: dict(excess=v["excess"], mdd=v["mdd"], trades_yr=v["trades_yr"], yearly=v["yearly"], spells=[(str(a), str(b), round(c, 4)) for a, b, c in v["spells"]]) for k, v in res.items()},
          open(D + "is_mining_results.json", "w"), ensure_ascii=False, indent=1)
