"""组合模拟（prereg-v1 §4 离场、§5 仓位）。

时序（每个交易日 t）：
  开盘：先执行 t−1 收盘标记的离场，再执行 t−1 收盘产生的入场（按优先级，受持仓数 / 单容器 / 总风险 / 现金约束）。
  收盘：对每个持仓先用「昨日生效的止损」判断收盘是否跌破（跌破则标记 t+1 开盘离场），
        再用今日收盘更新最高收盘、启用与上移移动止盈（只上不下）；然后按净值记账；再生成 t 日信号。
价格一律用面板里的后复权点位；成本每边 cost_per_side。
成交行 data_hole = 1（I-26：数据断档上的平盘占位，开盘是陈旧收盘的拷贝）不入场，记入 skipped「数据断档」，信号不保留——
与「无开盘价」同一处理；D 日开盘时 D−1 有没有海外 K 线已知，不用未来信息。
出场也一样（I-27）：成交行断档视同无开盘价，exit_flag 保留，顺延到第一个非断档行按其开盘成交。
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Params
from .panel import wide
from .signals import all_signals


@dataclass
class Position:
    container: str
    branch: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_px: float
    stop_level: float
    r_unit: float
    shares: float
    weight: float
    init_risk: float
    stop: float
    hi_close: float
    activated: bool = False
    exit_flag: str = ""


@dataclass
class Result:
    trades: pd.DataFrame
    skipped: pd.DataFrame
    nav: pd.Series
    invested: pd.Series
    holdings: pd.DataFrame          # date × container 的持仓市值占比
    params: Params
    start: pd.Timestamp
    end: pd.Timestamp


def simulate(panel: pd.DataFrame, p: Params, start, end, signals: pd.DataFrame = None) -> Result:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    O, H, L, C, A = (wide(panel, k) for k in ("open", "high", "low", "close", "atr20"))
    dates = [d for d in C.index if start <= d <= end]
    cols = list(C.columns)
    ci = {c: i for i, c in enumerate(cols)}
    Oa, Ca, Aa = O.to_numpy(), C.to_numpy(), A.to_numpy()
    Ha = wide(panel, "data_hole").reindex(index=C.index, columns=cols).to_numpy()
    di = {d: i for i, d in enumerate(C.index)}

    sig = all_signals(panel, p, start, end) if signals is None else signals
    sig_by_date = {}
    for s_ in sig.itertuples(index=False):                  # 一次性转成元组，避免逐日切 DataFrame
        sig_by_date.setdefault(s_.date, []).append(s_)

    cash, positions, pending = 1.0, {}, None
    last_close = {}                                   # 停牌时沿用最近收盘记账
    trades, skipped, nav_rows, inv_rows, hold_rows = [], [], [], [], []

    def mark(c, k):
        v = Ca[k, ci[c]]
        if np.isfinite(v):
            last_close[c] = v
        return last_close.get(c, np.nan)

    def close_trade(pos, d, px, reason):
        nonlocal cash
        cash += pos.shares * px * (1 - p.cost_per_side)
        r = (px * (1 - p.cost_per_side) - pos.entry_px * (1 + p.cost_per_side)) / pos.r_unit
        ret = px * (1 - p.cost_per_side) / (pos.entry_px * (1 + p.cost_per_side)) - 1
        trades.append(dict(container=pos.container, branch=pos.branch, signal_date=pos.signal_date,
                           entry_date=pos.entry_date, entry_px=pos.entry_px, stop_level=pos.stop_level,
                           r_unit=pos.r_unit, weight=pos.weight, init_risk=pos.init_risk,
                           exit_date=d, exit_px=px, exit_reason=reason, R=r, ret=ret,
                           mfe_R=(pos.hi_close - pos.entry_px) / pos.r_unit, activated=pos.activated))

    for d in dates:
        k = di[d]
        # ---------- 开盘：离场 ----------
        for c in list(positions):
            pos = positions[c]
            if pos.exit_flag:
                px = Oa[k, ci[c]]
                if np.isfinite(px) and Ha[k, ci[c]] != 1:      # 停牌或断档（I-27）则顺延到下一个有开盘价的非断档行
                    close_trade(pos, d, px, pos.exit_flag)
                    del positions[c]
        # ---------- 开盘：入场 ----------
        if pending is not None:
            nav_open = cash + sum(ps.shares * last_close.get(c, ps.entry_px) for c, ps in positions.items())
            for s in pending:
                c = s.container
                why = None
                px = Oa[k, ci[c]]
                if c in positions:
                    why = "已持有"
                elif len(positions) >= p.max_positions:
                    why = "持仓已满"
                elif Ha[k, ci[c]] == 1:
                    why = "数据断档"
                elif not np.isfinite(px):
                    why = "无开盘价"
                elif px <= s.stop_level:
                    why = "开盘已在失效位下方"
                if why is None:
                    r_unit = px - s.stop_level
                    w = min(p.risk_per_trade * px / r_unit, p.max_weight)          # I-06：1R 恰为 0.5% 净值
                    used_risk = sum(ps.init_risk for ps in positions.values())
                    if used_risk + w * r_unit / px > p.max_total_risk + 1e-12:
                        w = max(0.0, (p.max_total_risk - used_risk) * px / r_unit)
                    w = min(w, cash / (nav_open * (1 + p.cost_per_side)))           # I-08：不加杠杆
                    if w < p.min_weight:
                        why = "现金或风险额度不足"
                if why is not None:
                    skipped.append(dict(date=d, signal_date=s.date, container=c, branch=s.branch, reason=why))
                    continue
                shares = w * nav_open / px
                cash -= shares * px * (1 + p.cost_per_side)
                last_close.setdefault(c, px)
                positions[c] = Position(c, s.branch, s.date, d, px, s.stop_level, r_unit, shares, w,
                                        w * r_unit / px, s.stop_level, px)
            pending = None
        # ---------- 收盘：止损判断与移动止盈 ----------
        for c, pos in positions.items():
            cl = Ca[k, ci[c]]
            if not np.isfinite(cl) or pos.exit_flag:
                continue
            if cl < pos.stop:
                pos.exit_flag = "移动止盈" if pos.activated else "失效位"
                continue
            pos.hi_close = max(pos.hi_close, cl)
            if not pos.activated and cl >= pos.entry_px + p.activate_at_r * pos.r_unit:
                pos.activated = True
            if pos.activated and np.isfinite(Aa[k, ci[c]]):
                pos.stop = max(pos.stop, pos.hi_close - p.trail_atr * Aa[k, ci[c]])
        # ---------- 记账 ----------
        vals = {c: pos.shares * mark(c, k) for c, pos in positions.items()}
        nav = cash + sum(vals.values())
        nav_rows.append((d, nav))
        inv_rows.append((d, sum(vals.values()) / nav))
        hold_rows.append({"date": d, **{c: v / nav for c, v in vals.items()}})
        # ---------- 收盘：新信号（t+1 开盘成交） ----------
        if d in sig_by_date and d != dates[-1]:
            pending = sig_by_date[d]

    # 期末仍持有：按最后收盘估值（I-11），离场成本照扣
    for c, pos in list(positions.items()):
        close_trade(pos, dates[-1], last_close.get(c, pos.entry_px), "期末未平")

    nav = pd.Series(dict(nav_rows)).sort_index()
    return Result(
        trades=pd.DataFrame(trades),
        skipped=pd.DataFrame(skipped, columns=["date", "signal_date", "container", "branch", "reason"]),
        nav=nav,
        invested=pd.Series(dict(inv_rows)).sort_index(),
        holdings=pd.DataFrame(hold_rows).set_index("date").reindex(columns=cols).fillna(0.0),
        params=p, start=start, end=end,
    )


def random_entry_null(panel: pd.DataFrame, p: Params, start, end, n_signals: int, reps: int, seed: int = 0) -> np.ndarray:
    """I-17 零模型：同样的离场与仓位规则，随机容器 × 随机日期，信号数与 v1 相同；返回每次的期望 R。
    随机入场池与策略的可入行同一集合：断档行（data_hole = 1）不进池（I-26）。"""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    pool = panel[(panel["date"] >= start) & (panel["date"] < end) & panel["atr20"].gt(0) & panel["close"].notna()
                 & panel["data_hole"].eq(0)]
    pool = pool[["date", "container", "close", "atr20"]].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        s = pool.iloc[rng.choice(len(pool), size=min(n_signals, len(pool)), replace=False)].copy()
        s["branch"], s["state"], s["rs_1m"], s["z_month"] = "随机", "", np.nan, np.nan
        s["stop_level"] = s["close"] - p.stop_atr * s["atr20"]
        s["priority"] = rng.random(len(s))
        s = s.sort_values(["date", "priority"]).reset_index(drop=True)
        t = simulate(panel, p, start, end, signals=s).trades
        out.append(t["R"].mean() if len(t) else np.nan)
    return np.asarray(out)
