"""轮动面板 · 规则成绩单：读 data/panel_daily.csv，按进攻/防守两条规则出 2026 年信号 → data/signals_2026.csv、data/gaps_2026.csv。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np, json
P = pd.read_csv(f"{ROOT_S}/data/panel_daily.csv", parse_dates=["date"])
P = P[P.date >= "2026-01-01"].copy().sort_values(["container","date"])
dates = sorted(P.date.unique()); idx = {d:i for i,d in enumerate(dates)}
W = P.pivot(index="date", columns="container", values="close"); B = W["宽基-沪深300"]
K = P.pivot(index="date", columns="container", values="kell"); R = P.pivot(index="date", columns="container", values="rank_1m"); PR = P.pivot(index="date", columns="container", values="prem")
ENTRY = {"POP","XB","BNB"}; EXIT = {"DROP","XBD","EXH","BNBD"}
NAME = {"POP":"启动","XB":"回踩","BNB":"平台突破","EXH":"过热","DROP":"破位","XBD":"反弹遇阻","BNBD":"平台跌破","REV":"超跌反弹","TREND_UP":"上升中","TREND_DOWN":"下跌中","NEUTRAL":"无趋势"}
SRC = ["半导体","AI算力","宽基-科创50"]; DEF = ["红利","银行","黄金","现金"]
conts = [c for c in W.columns if c not in ("宽基-沪深300",)]
sig = []
# ---- 进攻信号：目的地进场态 & 排名<=5 & 溢价<20%，20 日内同容器只记一次；退出：危险态或 20 日
for c in conts:
    if c == "现金": continue
    last = -99
    for i, d in enumerate(dates):
        if i - last < 20: continue
        k = K.loc[d, c]; r = R.loc[d, c]; p = PR.loc[d, c]
        if k in ENTRY and r <= 5 and not (pd.notna(p) and p >= 0.2):
            # 退出
            j_exit = None
            for j in range(i+1, min(i+21, len(dates))):
                if K.loc[dates[j], c] in EXIT: j_exit = j; break
            j = j_exit if j_exit is not None else min(i+20, len(dates)-1)
            ret = W.loc[dates[j], c]/W.loc[d, c]-1; b = B.loc[dates[j]]/B.loc[d]-1
            sig.append(dict(mode="进攻", cont=c, entry=str(d.date()), state=NAME[k], rank=int(r), prem=None if pd.isna(p) else round(float(p),3),
                            exit=str(dates[j].date()), exit_why=(NAME[K.loc[dates[j], c]] if j_exit is not None else "20 日到期"), days=j-i, ret=round(float(ret),4), bench=round(float(b),4), excess=round(float(ret-b),4), open=(j==len(dates)-1 and j_exit is None)))
            last = i
# ---- 防守信号：源头三只里 >=2 只处于危险态/下跌中 且 至少一只当日为危险态；目的地 = 防守容器里当日排名最高；20 日内只记一次
last = -99
for i, d in enumerate(dates):
    if i - last < 20: continue
    ks = [K.loc[d, s] for s in SRC]
    if sum(k in EXIT or k=="TREND_DOWN" for k in ks) >= 2 and any(k in EXIT for k in ks):
        dest = min(DEF, key=lambda x: R.loc[d, x])
        j_exit = None
        for j in range(i+1, min(i+21, len(dates))):
            if all(K.loc[dates[j], s] in ("XB","BNB","POP","TREND_UP") for s in SRC[:2]): j_exit = j; break
        j = j_exit if j_exit is not None else min(i+20, len(dates)-1)
        ret = W.loc[dates[j], dest]/W.loc[d, dest]-1; src = float(np.mean([W.loc[dates[j], s]/W.loc[d, s]-1 for s in SRC])); b = B.loc[dates[j]]/B.loc[d]-1
        sig.append(dict(mode="防守", cont=dest, entry=str(d.date()), state="源头 "+"/".join(NAME[k] for k in ks), rank=int(R.loc[d, dest]), prem=None,
                        exit=str(dates[j].date()), exit_why=("源头转强" if j_exit is not None else "20 日到期"), days=j-i, ret=round(float(ret),4), bench=round(float(b),4), excess=round(float(ret-b),4), src=round(src,4), avoided=round(float(ret-src),4), open=(j==len(dates)-1 and j_exit is None)))
        last = i
S = pd.DataFrame(sig).sort_values("entry")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(S.to_string(index=False))
for m in ("进攻","防守"):
    s = S[(S["mode"]==m)&(~S.open)]
    if len(s): print(f"\n{m}: n={len(s)} 中位持有 {s.days.median():.0f} 日 中位超额 {s.excess.median():+.1%} 均值 {s.excess.mean():+.1%} 胜率 {(s.excess>0).mean():.0%} 最差 {s.excess.min():+.1%} 最好 {s.excess.max():+.1%}")
# ---- 下行 → 进场态 的间隔（ETA 参考）
gaps = []
for c in conts:
    if c=="现金": continue
    ks = K[c]; start=None
    for i,d in enumerate(dates):
        k = ks.loc[d]
        if start is None and k in ("DROP","XBD","BNBD"): start=i
        elif start is not None and k in ENTRY: gaps.append((c, str(dates[start].date()), str(d.date()), i-start)); start=None
G = pd.DataFrame(gaps, columns=["cont","from","to","days"])
print("\n下行→进场态 间隔: n=%d 中位 %.0f 日 25/75 分位 %.0f/%.0f" % (len(G), G.days.median(), G.days.quantile(.25), G.days.quantile(.75)))
S.to_csv(f"{ROOT_S}/data/signals_2026.csv", index=False); G.to_csv(f"{ROOT_S}/data/gaps_2026.csv", index=False)
# 当日状态快照
d = dates[-1]; snap = P[P.date==d].sort_values("rank_1m")[["container","rank_1m","rs_1m","rs_1w","vol_20_250","prem","ext","kell"]]
snap["state"] = snap.kell.map(NAME); print("\n", str(d.date())); print(snap.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
