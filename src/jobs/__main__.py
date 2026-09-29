"""python -m src.jobs daily  --rules config/ledger-rules.json [--date D] [--db data/ledger.sqlite] [--events-dir data/events] [--no-update]
                                                             （北京时间 05:00–09:30 运行：此时 A 股与美股的 D 日都已收盘）
python -m src.jobs replay --panel P --bench B --from D1 --to D2 --rules R --db 回放库.sqlite [--events-dir …]

daily：P1 update → 从 raw 现算面板（P2）→ 台账流程（本包）。定时与无人值守运行交 astra（replan §4 S3）。
replay：用历史面板逐日回放，只验流程（冒烟），不产出研究结论；回放库与正式台账分开。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

from src.data import runner as data_runner
from src.ledger.store import DEFAULT_DB, Ledger
from . import rules as R
from .daily import DailyJob
from .guard import mark_processed, preflight, processed_days
from .live import instruments, live_panel


def default_day() -> date:
    """A 股与海外都已收盘的最近日期（北京时间次晨运行时即上一个 A 股交易日）。"""
    return min(data_runner.last_complete("csi"), data_runner.last_complete("yahoo"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.jobs", description="台账每日任务")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily")
    d.add_argument("--date", type=date.fromisoformat, default=None, help="默认：A 股与海外都已收盘的最近日期")
    d.add_argument("--no-update", action="store_true", help="不先跑数据增量（raw 已是最新时用）")
    r = sub.add_parser("replay")
    r.add_argument("--panel", type=Path, required=True)
    r.add_argument("--bench", type=Path, required=True)
    r.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    r.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    for p in (d, r):
        p.add_argument("--rules", type=Path, required=True)
        p.add_argument("--db", type=Path, default=DEFAULT_DB if p is d else None, required=p is r)
        p.add_argument("--events-dir", type=Path, default=None)
    a = ap.parse_args(argv)
    rules = R.load_rule_config(a.rules)
    if not rules:
        print("规则配置里没有任何启用的规则（horizon_days / target_excess_pct / benchmark 需由 Cowork 填）", file=sys.stderr)
        return 2

    if a.cmd == "daily":
        day = a.date or default_day()
        if not a.no_update:
            failed = [r for r in data_runner.update(day) if not r.get("ok")]
            for r in failed:
                print(f"update 失败：{r.get('theme_id')} {r.get('file')}：{r.get('error', '')[:120]}", file=sys.stderr)
        cov = data_runner.OUT_DIR / "coverage.csv"
        panel, bench, problems = live_panel(data_runner.RAW_DIR, cov, day)
        blocking, notes = preflight(panel, bench, day.isoformat(), cov, processed_days())
        if blocking:
            print("\n".join(["运行前检查未通过，台账未动："] + blocking), file=sys.stderr)
            return 3
        L = Ledger(a.db)
        job = DailyJob(L, panel, bench, rules=rules, instruments=instruments(coverage_csv=data_runner.OUT_DIR / "coverage.csv"),
                       events_dir=a.events_dir)
        rep = job.run(day.isoformat())
        rep.skipped += problems + notes
        print(json.dumps(asdict(rep), ensure_ascii=False, indent=1))
        L.close()
        mark_processed(day.isoformat())
        return 0

    panel = pd.read_csv(a.panel, parse_dates=["date"])
    bench = pd.read_csv(a.bench, parse_dates=["date"]).set_index("date")["hs300"]
    state = {"now": ""}
    L = Ledger(a.db, clock=lambda: state["now"], replay=True)        # 正式台账库会被拒绝；回放库记为 replay 模式
    job = DailyJob(L, panel, bench, rules=rules, instruments=instruments(), events_dir=a.events_dir)
    days = sorted(d for d in panel["date"].dt.date.unique() if a.start <= d <= a.end)
    for day in days:
        state["now"] = f"{day.isoformat()}T16:00"
        rep = job.run(day.isoformat())
        if rep.changed() or rep.skipped:
            print(json.dumps(asdict(rep), ensure_ascii=False))
    print(json.dumps(L.summary(), ensure_ascii=False))
    L.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
