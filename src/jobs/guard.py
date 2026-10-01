"""每日任务的运行前检查：漏跑与数据新鲜度（停牌与数据迟到不能混为一谈）。

- D 必须是基准（H00300）的交易日，且基准已有 D 的行；
- A 股路由的研究序列（指数在交易日不会停牌）在 D 必须有行，缺了就是数据没到，停止运行而不是把候选当「无开盘价」作废；
  海外序列经 I-20 对齐后 D 日总有一行（没有新 K 线就是平盘），这里只剩「序列起点晚于 D」一种缺行，只记报告；
  海外平盘与疑似停更由 live_panel 报告（末尾连续平盘行数、最后一根 K 线日期）；
- 连续性：已处理过的交易日里若不含 D 的前一个基准交易日，说明漏跑，先按顺序补跑。
已处理的交易日记在台账库的 job_days 表（Ledger.processed_days / mark_processed），每成功跑完一天追加一行。
"""
from __future__ import annotations

import pandas as pd

from src.data import universe as U
from src.data.runner import A_SHARE_ROUTES


def preflight(panel: pd.DataFrame, bench: pd.Series, day: str, coverage: list[dict], done: set[str]) -> tuple[list[str], list[str]]:
    """coverage 是 market.sqlite 的当前 coverage（每容器一行）。返回 (阻断问题, 提示)。阻断问题非空时不跑台账流程。"""
    D = pd.Timestamp(day)
    blocking, notes = [], []
    if D not in set(bench.index):
        return [f"{day} 不是基准交易日或基准 H00300 尚未更新到 {day}"], notes
    earlier = [d for d in bench.index if d < D]
    prev = earlier[-1].date().isoformat() if earlier else None
    if done and prev and prev not in done and day not in done:
        blocking.append(f"漏跑 {prev}：先按顺序补跑（python -m src.jobs daily --date {prev}），再跑 {day}")
    have = set(panel.loc[panel["date"] == D, "container"])
    for c in coverage:
        if c.get("status") not in U.PANEL_STATUSES or not c.get("series_adj") or c["container"] in have:
            continue
        if c.get("route_used") in A_SHARE_ROUTES:
            blocking.append(f"{c['container']}（{c['route_used']}）在 {day} 没有行：数据未到，先跑 update")
        else:
            notes.append(f"{c['container']}（{c['route_used']}）在 {day} 没有行（对齐后本应每天有行：序列起点晚于 {day} 或未能读入）")
    return blocking, notes
