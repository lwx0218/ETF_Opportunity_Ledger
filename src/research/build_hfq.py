# -*- coding: utf-8 -*-
"""510880 红利ETF · 二十年后复权序列（锚在上市首日，永不改写历史）。
输入：腾讯不复权日线（2007-01-18→2019-12-31 与 2020→今 两段）+ 腾讯前复权（减法口径）同区间。
分红 = 不复权收盘 − 前复权收盘 这一偏移量的逐日下跳（除息日）。
后复权因子（标准口径）：F_t = Π_{除息日 e ≤ t} P_{e-1} / (P_{e-1} − D_e)，即分红按除息参考价再投资。
输出：data/kline_hfq_510880.csv（date,open,close,high,low,volume,raw_close,factor）、data/dividends_510880.csv。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np

D = f"{ROOT_S}/data/"
def rd(f): return pd.read_csv(D + f, parse_dates=["date"])
raw = pd.concat([rd("kline_raw_510880_2006_2019.csv"), rd("kline_raw_510880.csv")]).sort_values("date").drop_duplicates("date").reset_index(drop=True)
qfq = pd.concat([rd("kline_qfq_510880_2006_2019.csv"), rd("kline_long_510880.csv")]).sort_values("date").drop_duplicates("date").reset_index(drop=True)
assert (raw.date.values == qfq.date.values).all(), "日期不对齐"
assert np.allclose(raw.volume, qfq.volume), "成交量不一致"

# 2010 上半年腾讯高低价只给两位小数 → 用开收盘修正，保证 low ≤ open,close ≤ high
raw["high"] = raw[["high", "open", "close"]].max(axis=1); raw["low"] = raw[["low", "open", "close"]].min(axis=1)

off = (raw.close - qfq.close).round(3)
div = (off.shift(1) - off).round(3).fillna(0)
div[div.abs() <= 0.001] = 0
assert (div >= 0).all(), "偏移量出现上跳，检查数据"
ex = raw.loc[div > 0, ["date", "close"]].copy(); ex["div"] = div[div > 0].values
ex["prev_close"] = raw.close.shift(1)[div > 0].values
ex["yield_at_ex"] = ex["div"] / ex["prev_close"]
ex["year"] = ex.date.dt.year
ex[["date", "div", "prev_close", "yield_at_ex"]].to_csv(D + "dividends_510880.csv", index=False, float_format="%.4f")

# 后复权因子
step = np.where(div > 0, raw.close.shift(1) / (raw.close.shift(1) - div), 1.0)
step[0] = 1.0
F = pd.Series(step).cumprod()
h = raw.copy()
for c in ("open", "close", "high", "low"): h[c] = raw[c] * F
h["raw_close"] = raw.close; h["factor"] = F
h.to_csv(D + "kline_hfq_510880.csv", index=False, float_format="%.4f")

# 核对
print("行数", len(h), h.date.iloc[0].date(), "→", h.date.iloc[-1].date())
print("分红次数", len(ex), "累计现金", round(ex["div"].sum(), 3), "最终因子", round(float(F.iloc[-1]), 4))
print(ex.groupby("year")["div"].sum().round(3).to_dict())
r_raw = raw.close.iloc[-1] / raw.close.iloc[0] - 1; r_h = h.close.iloc[-1] / h.close.iloc[0] - 1
print(f"上市至今：不复权 {r_raw:+.1%} · 后复权全收益 {r_h:+.1%}")
# 逐年全收益
y = h.set_index("date").close.resample("YE").last(); y0 = h.close.iloc[0]
yr = (y / y.shift(1).fillna(y0) - 1)
print("逐年全收益：", {k.year: f"{v:+.1%}" for k, v in yr.items()})
# 日收益极值（查异常）
dr = h.close.pct_change()
print("最大单日", f"{dr.max():+.2%}", h.date[dr.idxmax()].date(), "最小单日", f"{dr.min():+.2%}", h.date[dr.idxmin()].date())
print("超过 ±10.5% 的日子：", h.date[dr.abs() > 0.105].dt.date.tolist())
