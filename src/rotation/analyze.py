"""轮动面板 · 第一步：读 data/kline_*.csv 与 data/nav_*.csv，用 etf_probe 的形态状态机逐日计算 17 个容器的状态向量 → data/panel_daily.csv。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np, json, importlib.util, sys
spec = importlib.util.spec_from_file_location("probe", f"{ROOT_S}/src/rotation/etf_probe.py")
# 避免 import akshare 失败：注入伪模块
import types; sys.modules.setdefault("akshare", types.ModuleType("akshare"))
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)

C = [("510300","宽基-沪深300","A"),("588000","宽基-科创50","A"),("512760","半导体","A"),("159516","半导体设备","A"),
     ("159819","AI算力","A"),("515880","通信","A"),("501018","原油","A"),("159825","农业","A"),("512800","银行","A"),
     ("510880","红利","A"),("518880","黄金","A"),("515220","煤炭","A"),("512400","有色","A"),("511880","现金","A"),
     ("501225","Q-全球半导体","Q"),("159509","Q-纳指科技","Q"),("513100","Q-纳指100","Q")]
D = f"{ROOT_S}/data/"
bench = pd.read_csv(D+"kline_510300.csv", parse_dates=["date"]).set_index("date")["close"]
rows = []
for code, name, line in C:
    h = pd.read_csv(D+f"kline_{code}.csv", parse_dates=["date"])
    h["amount"] = h["close"] * h["volume"] * 100  # 手→股，近似成交额(元)
    h = probe.kell_states(h)
    h["ret"] = h.close.pct_change()
    h["r21"] = h.close.pct_change(21); h["r63"] = h.close.pct_change(63); h["r5"] = h.close.pct_change(5)
    b = bench.reindex(h.date).ffill().values; bs = pd.Series(b, index=h.index)
    h["rs_1m"] = h.r21 - bs.pct_change(21); h["rs_3m"] = h.r63 - bs.pct_change(63); h["rs_1w"] = h.r5 - bs.pct_change(5)
    h["vol_pct"] = h.amount.rolling(250, min_periods=60).rank(pct=True)
    h["vol_20_250"] = h.amount.rolling(20).mean() / h.amount.rolling(250, min_periods=60).mean()
    h["vol_5_60"] = h.amount.rolling(5).mean() / h.amount.rolling(60).mean()
    try:
        nav = pd.read_csv(D+f"nav_{code}.csv", parse_dates=["date"])
        h = h.merge(nav, on="date", how="left"); h["nav"] = h["nav"].ffill(); h["prem"] = h.close/h.nav - 1
    except FileNotFoundError:
        h["prem"] = np.nan
    h["code"], h["container"], h["line"] = code, name, line
    rows.append(h)
P = pd.concat(rows, ignore_index=True)
P = P[P.date >= "2025-12-01"].copy()
P["rank_1m"] = P.groupby("date")["rs_1m"].rank(ascending=False, method="min")
P.to_csv(f"{ROOT_S}/data/panel_daily.csv", index=False)

EP = [("2026-03-02","原油","E1 霍尔木兹受阻，布伦特开盘+13%，原油LOF溢价>26%",["半导体","宽基-科创50","AI算力"]),
      ("2026-05-11","Q-全球半导体","E2 全球芯片LOF溢价46–47%，上交所重点监控",[]),
      ("2026-06-01","Q-全球半导体","E3 全球芯片LOF/纳指科技ETF/中韩半导体ETF同日临停",[]),
      ("2026-08-31","农业","E4 粮食ETF+6.3%，AI核心标的低迷，半导体ETF净流出",["半导体","AI算力","宽基-科创50","通信"]),
      ("2026-09-10","银行","E5 银行主题ETF全线涨，粮食/农产品全线跌，成交连续4日<2万亿",["半导体","AI算力","宽基-科创50","通信"])]
dates = sorted(P.date.unique())
cols = ["container","rank_1m","rs_1m","rs_1w","vol_20_250","vol_5_60","prem","ext","kell"]
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 100)
for d, dest, why, srcs in EP:
    d = pd.Timestamp(d); ds = [x for x in dates if x <= d]; d0 = ds[-1]; d5 = ds[-6]; d10 = ds[-11]
    print("\n=====", why, "\n目的地:", dest, "| t-5 =", d5.date(), "| t =", d0.date())
    for tag, dd in (("t-5", d5), ("t", d0)):
        s = P[P.date==dd].sort_values("rank_1m")[cols]
        print(f"--- {tag} {dd.date()}"); print(s.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    # 源头在 t-10..t 的 Kell 状态序列
    for sname in srcs + [dest]:
        seq = P[(P.container==sname)&(P.date>=d10)&(P.date<=d0)].sort_values("date")
        print(f"{sname} t-10..t kell:", " ".join(seq.kell.tolist()), "| rank_1m:", " ".join(str(int(x)) for x in seq.rank_1m), "| prem:", " ".join("" if pd.isna(x) else f"{x:.0%}" for x in seq.prem))
