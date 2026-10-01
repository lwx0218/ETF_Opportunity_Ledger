"""python -m src.jobs daily  --rules config/ledger-rules.json [--date D] [--db data/ledger.sqlite] [--market data/market.sqlite]
                            [--events-dir data/events] [--no-update]
                                                             （北京时间 15:30 之后运行：A 股 D 日已收盘；海外容器按 I-20 用 D−1 的 K 线，也已收盘）
python -m src.jobs replay --panel panel-D.sqlite --from D1 --to D2 --rules R --db 回放库.sqlite [--events-dir …] [--calendar 库]

daily：P1 update（写 market.sqlite）→ 从库现算面板（P2）→ 台账流程（本包）。定时与无人值守运行交 astra（replan §4 S3）。
replay：用 build 产出的面板库逐日回放，只验流程（冒烟），不产出研究结论；回放库与正式台账分开，等权日收益记在回放库自己的 ew_daily 表。
交易日历：market.sqlite 的 calendar 表（v1.1-e；表空时月末与评分截止退回工作日规则）。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

from src.data import db as DB
from src.data import runner as data_runner
from src.indicators.calendar import load_trading_days
from src.ledger.store import DEFAULT_DB, Ledger
from src.research.prereg_v1.panel import read_table
from . import rules as R
from .daily import DailyJob
from .guard import preflight
from .live import coverage, instruments, live_panel


def default_day() -> date:
    """A 股已收盘的最近日期。I-20 之后海外容器在 D 日用本地 D−1 的 K 线，北京 15:30 时它早已收盘，不必等到次晨。"""
    return data_runner.last_complete("csi")


def calendar_or_exit(db: Path):
    try:
        return load_trading_days(db)
    except ValueError as e:
        raise SystemExit(f"交易日历不可用，台账未动：{e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.jobs", description="台账每日任务")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily")
    d.add_argument("--date", type=date.fromisoformat, default=None, help="默认：A 股已收盘的最近日期")
    d.add_argument("--no-update", action="store_true", help="不先跑数据增量（库已是最新时用）")
    d.add_argument("--market", type=Path, default=DB.MARKET_DB, help="行情库")
    r = sub.add_parser("replay")
    r.add_argument("--panel", type=Path, required=True, help="build 产出的面板库 panel-D.sqlite")
    r.add_argument("--bench", type=Path, default=None, help="默认与 --panel 同一个库")
    r.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    r.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    r.add_argument("--calendar", type=Path, default=DB.MARKET_DB,
                   help="带交易日历的库（market.sqlite 或研究数据包；只影响评分截止，面板的月末已在建面板时定好）")
    for p in (d, r):
        p.add_argument("--rules", type=Path, required=True)
        p.add_argument("--db", type=Path, default=DEFAULT_DB if p is d else None, required=p is r)
        p.add_argument("--events-dir", type=Path, default=None)
    a = ap.parse_args(argv)
    rule_problems: list[str] = []
    rules = R.load_rule_config(a.rules, rule_problems)
    for x in rule_problems:
        print(f"规则配置：{x}", file=sys.stderr)
    if not rules:
        print(f"规则配置里没有启用的规则：confirmed_terms 须为 {R.TERMS_VERSION}、规则 enabled 为 true（V1 结论前全部关闭，A7）",
              file=sys.stderr)
        return 2

    if a.cmd == "daily":
        day = a.date or default_day()
        if not a.no_update:
            failed = [r for r in data_runner.update(day, db=a.market) if not r.get("ok")]
            for r in failed:
                print(f"update 失败：{r.get('theme_id')} {r.get('code')}/{r.get('adj')}：{(r.get('error') or '')[:120]}", file=sys.stderr)
        trading_days = calendar_or_exit(a.market)
        panel, bench, bench_open, problems = live_panel(a.market, day, trading_days)
        covs = coverage(a.market)
        L = Ledger(a.db)
        try:
            blocking, notes = preflight(panel, bench, day.isoformat(), covs, L.processed_days())
            if blocking:
                print("\n".join(["运行前检查未通过，台账未动："] + blocking), file=sys.stderr)
                return 3
            job = DailyJob(L, panel, bench, rules=rules, instruments=instruments(covs=covs), events_dir=a.events_dir,
                           bench_open=bench_open, trading_days=trading_days)
            rep = job.run(day.isoformat())
            if rep.blocked:
                print(f"台账未动：{rep.blocked}", file=sys.stderr)
                return 3
            L.mark_processed(day.isoformat())
        finally:
            L.close()
        rep.skipped += rule_problems + problems + notes + ([] if trading_days is not None else [f"{a.market} 里没有交易日历：月末与评分截止按工作日规则"])
        print(json.dumps(asdict(rep), ensure_ascii=False, indent=1))
        return 0

    panel = read_table(a.panel, "panel").assign(date=lambda x: pd.to_datetime(x["date"]))
    b = read_table(a.bench or a.panel, "bench").assign(date=lambda x: pd.to_datetime(x["date"])).set_index("date")
    bench = b["hs300"]
    bench_open = b["hs300_open"] if "hs300_open" in b else None
    trading_days = calendar_or_exit(a.calendar)
    state = {"now": ""}
    L = Ledger(a.db, clock=lambda: state["now"], replay=True)        # 正式台账库会被拒绝；回放库记为 replay 模式
    job = DailyJob(L, panel, bench, rules=rules, instruments=instruments(), events_dir=a.events_dir,
                   bench_open=bench_open, trading_days=trading_days)
    days = sorted(d for d in panel["date"].dt.date.unique() if a.start <= d <= a.end)
    for day in days:
        state["now"] = f"{day.isoformat()}T16:00"
        rep = job.run(day.isoformat())
        if rep.blocked:
            print(f"台账未动：{rep.blocked}", file=sys.stderr)
            L.close()
            return 3
        if rep.changed() or rep.skipped:
            print(json.dumps(asdict(rep), ensure_ascii=False))
    print(json.dumps(L.summary(), ensure_ascii=False))
    L.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
