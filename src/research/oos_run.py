# -*- coding: utf-8 -*-
"""样本外 2017-01-01 → 2026-09-15：冻结的两条规则只跑一次；再做 5 年设计 / 1 年检验的逐年滚动。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
from enh_engine import *
import json
d, me = load()
OOS0, OOS1 = "2017-01-01", "2026-09-15"
frozen = {"A 趋势 10m（Faber）": sig_trend(me, 10).fillna(1.0), "B 回撤 出25/回10": sig_dd(me, 0.25, 0.10)}
print(f"## 样本外 {OOS0}→{OOS1}（冻结规则，只跑一次）\n")
rows = ["| 规则 | 对持有超额 | 最大回撤 策略/持有 | 每年交易 | 在场 | 每次离场躲过(中位) | 离场命中 | 最大踏空 | 剔 2018 · 逐年超额 |", "|---|---|---|---|---|---|---|---|---|"]
out = {}
for k, s in frozen.items():
    r = run(d, me, s, OOS0, OOS1); out[k] = r
    rows.append(fmt(k, r, ex=2018))
bh = out[list(out)[0]]
print(f"持有不动 {bh['bh']:+.1%}，最大回撤 {bh['mdd_bh']:+.0%}\n")
print("\n".join(rows))
for k, r in out.items():
    print(f"\n{k} 离场段：", [(str(a), str(b), f"{c:+.1%}") for a, b, c in r["spells"]])
    # 参数 ±20%
    if k.startswith("A"):
        p = [run(d, me, sig_trend(me, n).fillna(1.0), OOS0, OOS1)["excess"] for n in (8, 12)]
    else:
        p = [run(d, me, sig_dd(me, 0.20, 0.08), OOS0, OOS1)["excess"], run(d, me, sig_dd(me, 0.30, 0.12), OOS0, OOS1)["excess"]]
    print(f"{k} 参数 −20%/+20% 超额：{p[0]:+.1%} / {p[1]:+.1%}")

# 验收（预注册 §4）
print("\n## 验收")
for k, r in out.items():
    c1 = r["excess"] > 0; c2 = r["mdd"] >= r["mdd_bh"] * (2 / 3); c3 = r["trades_yr"] <= 3
    print(f"- {k}：① 超额>0 {'✓' if c1 else '✗'}（{r['excess']:+.1%}）· ② 回撤减少≥1/3 {'✓' if c2 else '✗'}（{r['mdd']:+.0%} vs {r['mdd_bh']:+.0%}）· ③ 每年≤3 次 {'✓' if c3 else '✗'}（{r['trades_yr']:.1f}）→ {'通过' if c1 and c2 and c3 else '不通过'}")

# ---------- 滚动：5 年设计 / 1 年检验 ----------
print("\n## 滚动检验（每年用前 5 年选超额最高的配置，用于下一年；配置集合 = 样本内 §2.1 的粗网格）")
def configs():
    cf = {}
    for n in (6, 10, 12): cf[f"A{n}"] = sig_trend(me, n).fillna(1.0)
    for x in (0.10, 0.15, 0.20, 0.25):
        for y in (0.10, 0.20): cf[f"B{int(x*100)}/{int(y*100)}"] = sig_dd(me, x, y)
    for n in (6, 10, 12): cf[f"C1_{n}"] = sig_mkt_trend(me, n).fillna(1.0)
    for n in (3, 6): cf[f"C2_{n}"] = sig_rs(me, n, "hs300").fillna(1.0)
    return cf
cf = configs()
roll = []
for Y in range(2012, 2027):
    d0, d1 = f"{Y-5}-01-01", f"{Y-1}-12-31"; t0, t1 = f"{Y}-01-01", f"{Y}-12-31" if Y < 2026 else "2026-09-15"
    best = max(cf, key=lambda k: run(d, me, cf[k], d0, d1)["excess"])
    r = run(d, me, cf[best], t0, t1)
    roll.append((Y, best, r["excess"], r["bh"], r["total"]))
    print(f"- {Y}：选 {best}（设计期 {Y-5}–{Y-1}）→ 当年超额 {r['excess']:+.1%}（持有 {r['bh']:+.1%}）")
cum = np.prod([1 + x[2] for x in roll]) - 1
print(f"滚动 2012–2026 累计超额：{cum:+.1%}；正超额年数 {sum(1 for x in roll if x[2] > 0)}/{len(roll)}")
json.dump(dict(oos={k: dict(excess=v["excess"], mdd=v["mdd"], mdd_bh=v["mdd_bh"], trades_yr=v["trades_yr"], yearly=v["yearly"], spells=[(str(a), str(b), round(c, 4)) for a, b, c in v["spells"]]) for k, v in out.items()},
               roll=roll), open(D + "oos_results.json", "w"), ensure_ascii=False, indent=1)
