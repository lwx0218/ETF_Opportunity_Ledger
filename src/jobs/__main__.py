"""python -m src.jobs daily  --rules config/ledger-rules.json [--date D] [--db data/ledger.sqlite] [--events-dir data/events] [--no-update]
                                                             （北京时间 15:30 之后运行：A 股 D 日已收盘；海外容器按 I-20 用 D−1 的 K 线，也已收盘）
python -m src.jobs replay --panel P --bench B --from D1 --to D2 --rules R --db 回放库.sqlite [--events-dir …] [--calendar 日历文件]

daily：P1 update → 从 raw 现算面板（P2）→ 台账流程（本包）。定时与无人值守运行交 astra（replan §4 S3）。
replay：用历史面板逐日回放，只验流程（冒烟），不产出研究结论；回放库与正式台账分开，等权日收益也记在回放库旁边的文件里。
交易日历：data/calendar/sse-trading-days.csv（v1.1-e；没有时月末与评分截止退回工作日规则）。
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
from src.indicators.calendar import CALENDAR, load_trading_days
from src.ledger.store import DEFAULT_DB, Ledger
from . import rules as R
from .daily import DailyJob
from .ew import EW_PATH
from .guard import mark_processed, preflight, processed_days
from .live import instruments, live_panel


def default_day() -> date:
    """A 股已收盘的最近日期。I-20 之后海外容器在 D 日用本地 D−1 的 K 线，北京 15:30 时它早已收盘，不必等到次晨。"""
    return data_runner.last_complete("csi")


def ew_path_for(db: Path) -> Path:
    """正式台账用 data/ledger/ew_daily.csv（v1.1-e）；其他库各用自己旁边的文件，互不污染。"""
    if Path(db).resolve() == DEFAULT_DB.resolve():
        return EW_PATH
    return Path(db).with_name(Path(db).stem + ".ew_daily.csv")


def unpaired(db: Path) -> str:
    """新库配旧等权文件 = 冻结的 cf_ew_level 来自别的面板（v1.1-e 要求两者是一对）。"""
    ew = ew_path_for(db)
    if not Path(db).exists() and ew.exists():
        return f"{db} 是新库，但等权日收益文件 {ew} 已存在（来自之前的库或面板）：确认后删掉或移走它再跑"
    return ""


def calendar_or_exit(path: Path):
    try:
        return load_trading_days(path)
    except ValueError as e:
        raise SystemExit(f"交易日历文件不可用，台账未动：{e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.jobs", description="台账每日任务")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily")
    d.add_argument("--date", type=date.fromisoformat, default=None, help="默认：A 股已收盘的最近日期")
    d.add_argument("--no-update", action="store_true", help="不先跑数据增量（raw 已是最新时用）")
    r = sub.add_parser("replay")
    r.add_argument("--panel", type=Path, required=True)
    r.add_argument("--bench", type=Path, required=True)
    r.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    r.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    r.add_argument("--calendar", type=Path, default=CALENDAR, help="交易日历文件（只影响评分截止；面板的月末已在建面板时定好）")
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
            failed = [r for r in data_runner.update(day) if not r.get("ok")]
            for r in failed:
                print(f"update 失败：{r.get('theme_id')} {r.get('file')}：{r.get('error', '')[:120]}", file=sys.stderr)
        cov = data_runner.OUT_DIR / "coverage.csv"
        trading_days = calendar_or_exit(CALENDAR)
        panel, bench, bench_open, problems = live_panel(data_runner.RAW_DIR, cov, day, trading_days)
        blocking, notes = preflight(panel, bench, day.isoformat(), cov, processed_days())
        if blocking:
            print("\n".join(["运行前检查未通过，台账未动："] + blocking), file=sys.stderr)
            return 3
        if unpaired(a.db):
            print(f"台账未动：{unpaired(a.db)}", file=sys.stderr)
            return 3
        L = Ledger(a.db)
        job = DailyJob(L, panel, bench, rules=rules, instruments=instruments(coverage_csv=data_runner.OUT_DIR / "coverage.csv"),
                       events_dir=a.events_dir, ew_path=ew_path_for(a.db), bench_open=bench_open, trading_days=trading_days)
        rep = job.run(day.isoformat())
        L.close()
        if rep.blocked:
            print(f"台账未动：{rep.blocked}", file=sys.stderr)
            return 3
        rep.skipped += rule_problems + problems + notes + ([] if trading_days is not None else [f"没有交易日历文件 {CALENDAR}：月末与评分截止按工作日规则"])
        print(json.dumps(asdict(rep), ensure_ascii=False, indent=1))
        mark_processed(day.isoformat())
        return 0

    panel = pd.read_csv(a.panel, parse_dates=["date"])
    b = pd.read_csv(a.bench, parse_dates=["date"]).set_index("date")
    bench = b["hs300"]
    bench_open = b["hs300_open"] if "hs300_open" in b else None
    if unpaired(a.db):
        print(f"台账未动：{unpaired(a.db)}", file=sys.stderr)
        return 3
    state = {"now": ""}
    L = Ledger(a.db, clock=lambda: state["now"], replay=True)        # 正式台账库会被拒绝；回放库记为 replay 模式
    job = DailyJob(L, panel, bench, rules=rules, instruments=instruments(), events_dir=a.events_dir, ew_path=ew_path_for(a.db),
                   bench_open=bench_open, trading_days=calendar_or_exit(a.calendar))
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
