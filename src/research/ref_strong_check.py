#!/usr/bin/env python3
"""ref/auto_filter_stock 强势股回测的最小验证（2026-09-27）。

只读仓库内既有文件，不取新数据、不改原策略、不调参：
  ref/auto_filter_stock/strong_backtest_results/{1day,2day,1week}_详细交易记录.csv
  ref/auto_filter_stock/data/daily_screening_results.csv
  ref/auto_filter_stock/data/CS300.dta（本地文件，已移出 Git）

四项检验：
  1. 逐笔重算：补印花税 0.05%（卖出）与过户费 0.001%（双向），重建净值，按「距前高回落比例」算回撤
  2. 收益集中度：1–7 月 vs 8–10 月；去掉最好 1/2/3 个自然周
  3. 排名区分度：每日第 1–5 名 vs 第 6–10 名（按日配对）
  4. 对沪深300 回归：β、β 调整后每期超额（α）及 t 值；沪深300 按同一执行口径
     （买入日开盘 → 卖出日 (最高+最低)/2）
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "ref" / "auto_filter_stock"
STAMP = 0.0005      # 卖出印花税，2023-08-28 起
TRANSFER = 0.00001  # 过户费，双向
STRATS = {"1day": "持有1天", "2day": "持有2天", "1week": "持有1周"}
SPLIT = pd.Timestamp("2025-07-31")


def load_index():
    c = pd.read_stata(REF / "data" / "CS300.dta")
    c["Trddt"] = pd.to_datetime(c["Trddt"])
    return c.set_index("Trddt")


def load_screen():
    s = pd.read_csv(REF / "data" / "daily_screening_results.csv")
    s["d"] = pd.to_datetime(s["筛选日期"])
    s["code"] = s["股票代码"].astype(str)
    return s


def pair_trades(key):
    """把买入行和随后的卖出行配成逐笔交易；同一买入日为一批。"""
    t = pd.read_csv(REF / "strong_backtest_results" / f"{key}_详细交易记录.csv")
    t["日期"] = pd.to_datetime(t["日期"])
    open_pos, trades = {}, []
    cash_after_buy = {}
    for _, r in t.iterrows():
        if r["操作类型"] == "买入":
            open_pos[r["股票代码"]] = r
            cash_after_buy[r["日期"]] = r["现金余额"]
        elif r["操作类型"] == "卖出":
            b = open_pos.pop(r["股票代码"])
            trades.append({
                "buy": b["日期"], "sell": r["日期"], "code": str(r["股票代码"]),
                "buy_amt": b["金额"], "buy_fee": b["手续费"],
                "sell_amt": r["金额"], "sell_fee": r["手续费"],
            })
    tr = pd.DataFrame(trades)
    tr["cost0"] = tr.buy_amt + tr.buy_fee
    tr["proc0"] = tr.sell_amt - tr.sell_fee
    tr["cost1"] = tr.cost0 + tr.buy_amt * TRANSFER
    tr["proc1"] = tr.proc0 - tr.sell_amt * (STAMP + TRANSFER)
    tr["r0"] = tr.proc0 / tr.cost0 - 1
    tr["r1"] = tr.proc1 / tr.cost1 - 1
    return t, tr, cash_after_buy, len(open_pos)


def batches(tr, cash_after_buy, idx):
    g = tr.groupby(["buy", "sell"]).agg(cost0=("cost0", "sum"), proc0=("proc0", "sum"),
                                         cost1=("cost1", "sum"), proc1=("proc1", "sum"),
                                         n=("code", "size")).reset_index()
    g["r0"] = g.proc0 / g.cost0 - 1
    g["r1"] = g.proc1 / g.cost1 - 1
    # 投入比例（整手取整留下的现金不参与收益）
    g["w"] = g.cost0 / (g.cost0 + g["buy"].map(cash_after_buy))
    g["p0"] = g.w * g.r0
    g["p1"] = g.w * g.r1
    mid = (idx["Hiindex"] + idx["Loindex"]) / 2
    g["m"] = mid.reindex(g["sell"]).values / idx["Opnindex"].reindex(g["buy"]).values - 1
    return g


def maxdd(ret):
    eq = (1 + ret).cumprod()
    return (eq / eq.cummax() - 1).min()


def comp(x):
    return (1 + x).prod() - 1


def ols(y, x):
    X = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    s2 = e @ e / (len(y) - 2)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return b, b / se


def main():
    idx = load_index()
    scr = load_screen()
    sdates = sorted(scr["d"].unique())
    rank = scr.set_index(["d", "code"])["排名"]
    for key, name in STRATS.items():
        t, tr, cab, n_open = pair_trades(key)
        g = batches(tr, cab, idx)
        # --- 1. 重算 ---
        last_sell = g["sell"].max()
        rep = t.loc[t["日期"] == last_sell, "总价值"].iloc[0] / 1e6 - 1
        print(f"\n=== {name}（{len(tr)} 笔，{len(g)} 批，期末未平 {n_open} 笔）===")
        print(f"[1] 至最后一次卖出日 {last_sell.date()}：报表 {rep:+.1%}｜本脚本原口径 {comp(g.p0):+.1%}"
              f"｜补印花税+过户费 {comp(g.p1):+.1%}｜沪深300 同口径 {comp(g.m):+.1%}")
        print(f"    最大回撤（批次净值，距前高）：原口径 {maxdd(g.p0):.1%}｜补税后 {maxdd(g.p1):.1%}"
              f"｜沪深300 {maxdd(g.m):.1%}")
        # --- 2. 集中度 ---
        h1, h2 = g[g.sell <= SPLIT], g[g.sell > SPLIT]
        print(f"[2] 1–7 月：策略 {comp(h1.p1):+.1%} vs 沪深300 {comp(h1.m):+.1%}（{len(h1)} 批）"
              f"｜8–10 月：策略 {comp(h2.p1):+.1%} vs 沪深300 {comp(h2.m):+.1%}（{len(h2)} 批）")
        wk = g.groupby(g.sell.dt.to_period("W"))["p1"].apply(comp).sort_values(ascending=False)
        drops = [comp(wk.iloc[k:]) for k in (1, 2, 3)]
        print(f"    共 {len(wk)} 周；最好 3 周 {', '.join(f'{p}: {v:+.1%}' for p, v in wk.head(3).items())}")
        print(f"    去掉最好 1/2/3 周后累计：{drops[0]:+.1%} / {drops[1]:+.1%} / {drops[2]:+.1%}")
        # --- 3. 排名 ---
        def scr_date(b):
            prev = [d for d in sdates if d < b]
            return prev[-1] if prev else b
        tr["rank"] = [rank.get((scr_date(b), c), np.nan) for b, c in zip(tr.buy, tr.code)]
        tr["top"] = tr["rank"] <= 5
        daily = tr.groupby(["buy", "top"])["r1"].mean().unstack().dropna()
        diff = daily[True] - daily[False]
        tt = diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))
        print(f"[3] 排名缺失 {tr['rank'].isna().sum()} 笔｜每笔均值：前5 {tr.loc[tr.top,'r1'].mean():+.2%}"
              f" vs 后5 {tr.loc[~tr.top,'r1'].mean():+.2%}｜按批配对差 {diff.mean():+.2%}，t = {tt:.2f}（{len(diff)} 批）")
        # --- 4. β / α ---
        (a, beta), (ta, tb) = ols(g.r1.values, g.m.values)
        print(f"[4] β = {beta:.2f}（t {tb:.1f}）｜α = 每批 {a:+.2%}，t = {ta:.2f}"
              f"｜β 调整后累计（r − β·r_m 复利）{comp(g.r1 - beta * g.m):+.1%}")
        for lab, sub in (("1–7 月", h1), ("8–10 月", h2)):
            (a2, b2), (ta2, _) = ols(sub.r1.values, sub.m.values)
            print(f"    {lab}：β {b2:.2f}，α 每批 {a2:+.2%}，t = {ta2:.2f}")


if __name__ == "__main__":
    main()
