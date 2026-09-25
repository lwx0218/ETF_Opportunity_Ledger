# -*- coding: utf-8 -*-
"""红利股息率 − 10 年国债利差 · 描述性检查（etf-dividend-enhancement-prereg §6.4 的数字来源；只有 2014 起的数据，不算检验）。
股息率 = 最近一次年度分红 / 当月末不复权价；国债 = OECD 月度（data/cgb10y_monthly_oecd.csv）。
原为 2026-09-17 会话内一次性脚本，2026-09-25 留存为文件；删去了原脚本里一段未产出结果的逐年表（因分组键错误输出为空，未被引用）。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np

D = f"{ROOT_S}/data/"
d = pd.read_csv(D + "kline_hfq_510880.csv", parse_dates=["date"]); d["m"] = d.date.dt.to_period("M")
me = d.groupby("m").agg(date=("date", "last"), close=("close", "last"), raw=("raw_close", "last")).reset_index()
div = pd.read_csv(D + "dividends_510880.csv", parse_dates=["date"]); div["m"] = div.date.dt.to_period("M")
last_div = pd.Series(np.nan, index=me.m)
for _, r in div.iterrows(): last_div.loc[r.m:] = r["div"]
me["last_div"] = last_div.values
y = pd.read_csv(D + "cgb10y_monthly_oecd.csv"); y["m"] = pd.PeriodIndex(y.period, freq="M")
me = me.merge(y[["m", "yield"]], on="m", how="left")
me["dy"] = me.last_div / me.raw * 100; me["spread"] = me.dy - me["yield"]
me["fwd12"] = me.close.shift(-12) / me.close - 1; me["fwd6"] = me.close.shift(-6) / me.close - 1
x = me[(me.m >= "2014-01") & (me.m <= "2025-09")].dropna(subset=["spread", "fwd12"]).copy()
print("样本 2014-01 → 2025-09 月度", len(x), "行；股息率中位", round(x.dy.median(), 2), "利差中位", round(x.spread.median(), 2))
x["q"] = pd.qcut(x.spread, 4, labels=["Q1 最窄", "Q2", "Q3", "Q4 最宽"])
print(x.groupby("q", observed=True).agg(n=("fwd12", "size"), spread_lo=("spread", "min"), spread_hi=("spread", "max"), fwd12_med=("fwd12", "median"),
      fwd12_mean=("fwd12", "mean"), fwd6_med=("fwd6", "median"), pos12=("fwd12", lambda s: (s > 0).mean())).round(3).to_string())
print("Spearman(利差, 12m前向):", round(x[["spread", "fwd12"]].corr(method="spearman").iloc[0, 1], 3),
      " (股息率单独):", round(x[["dy", "fwd12"]].corr(method="spearman").iloc[0, 1], 3),
      " (国债单独):", round(x[["yield", "fwd12"]].corr(method="spearman").iloc[0, 1], 3))
print("当前（2026-08 月末）：股息率", round(me.dy.iloc[-2], 2), "国债", me["yield"].dropna().iloc[-1], "利差", round(me.spread.dropna().iloc[-1], 2))
