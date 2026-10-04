"""python -m src.data <命令>（库默认 data/market.sqlite，--db 可换）

    probe    [--end D] [--start D] [--only T01,T02] [--record DIR]   → coverage 写进库
    backfill --end 2026-09-30 [--start D] [--exec-start D] [--only …] → bars + coverage
    update   [--end D] [--only …]                                     增量（往回多拉 10 天）
    calendar <交易日清单文件> [--replace]                               astra 生成的交易日 → calendar 表
    package  --end 2026-09-30 [--force] [--out-dir outputs]           → outputs/research-package-<end>.sqlite（+ .MANIFEST.json）
    verify   <包.sqlite>                                               sha256、integrity_check、行数、截断、来源
    compare  <参考.csv> <code> [--adj raw|hfq] [--out diff.csv]        重叠区间逐日比对收盘
    offline-restore --source-run-id N --recorded-dir DIR [--apply]  H00300 原文件恢复，默认只读
    preflight --end D [--start D]                                只读预检，默认从官方日历首日开始
    upgrade-date-constraints [--apply]                         显式升级旧 market-v1 日期约束，默认只读
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import db as DB
from . import runner


def _d(s: str) -> date:
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.data", description="ETF 前向机会台账 · 数据层")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("probe", "backfill", "update", "package"):
        p = sub.add_parser(name)
        p.add_argument("--end", type=_d, default=date.today() if name in ("probe", "update") else None,
                       required=name in ("backfill", "package"))
        if name in ("probe", "backfill"):
            p.add_argument("--start", type=_d, default=runner.DEFAULT_START, help="研究序列起点；不要为省请求而调晚，会丢设计期")
        if name == "backfill":
            p.add_argument("--exec-start", type=_d, default=None, help="只缩短执行 ETF 的起点（东财上市前空段多、易限流时用）")
        if name != "package":
            p.add_argument("--only", type=lambda s: [x.strip() for x in s.split(",") if x.strip()], default=None,
                           help="只跑这些 theme_id，逗号分隔")
        if name == "probe":
            p.add_argument("--record", type=Path, default=None, help="把原始响应存到该目录（替换构造的 fixtures 用）")
        if name == "package":
            p.add_argument("--force", action="store_true")
            p.add_argument("--out-dir", type=Path, default=runner.PKG_ROOT)
    p = sub.add_parser("calendar")
    p.add_argument("file", type=Path)
    p.add_argument("--replace", action="store_true", help="整表换成该文件（默认与已有的日子取并集）")
    p = sub.add_parser("verify")
    p.add_argument("package", type=Path)
    p = sub.add_parser("compare")
    p.add_argument("ref", type=Path)
    p.add_argument("code")
    p.add_argument("--adj", choices=["raw", "hfq"], default="raw")
    p.add_argument("--out", type=Path, default=None)
    p = sub.add_parser("offline-restore", help="离线恢复 H00300 与 T01 研究 coverage；默认 dry-run")
    p.add_argument("--source-run-id", type=int, required=True, help="已有 requests 所属的 probe / backfill 作业")
    p.add_argument("--recorded-dir", type=Path, required=True, help="原响应所在目录")
    p.add_argument("--apply", action="store_true", help="显式原子写入；省略时完全只读")
    p = sub.add_parser("preflight", help="只读质量预检；未达到 research_ready 时退出 1")
    p.add_argument("--end", type=_d, required=True)
    p.add_argument("--start", type=_d, default=None, help="请求窗口起点；省略时使用官方日历首日")
    p = sub.add_parser("upgrade-date-constraints", help="审计旧 market-v1 日期；显式 --apply 才升级约束")
    p.add_argument("--apply", action="store_true", help="原子追加约束，不改写历史数据")
    for name, sp in sub.choices.items():
        if name != "verify":
            sp.add_argument("--db", type=Path, default=DB.MARKET_DB)
    a = ap.parse_args(argv)

    if a.cmd == "probe":
        covs = runner.probe(a.end, start=a.start, only=a.only, record=a.record, db=a.db)
        panel = [c for c in covs if c["status"] in ("retained", "flagged")]
        print(f"面板容器 {len(panel)}：有路由 {sum(1 for c in panel if c['route_used'])}，"
              f"error {sum(1 for c in panel if c['error'])} → {a.db}")
    elif a.cmd == "backfill":
        runner.backfill(a.end, start=a.start, exec_start=a.exec_start, only=a.only, db=a.db)
    elif a.cmd == "update":
        rep = runner.update(a.end, only=a.only, db=a.db)
        print(f"更新 {sum(1 for r in rep if r.get('ok'))} / {len(rep)} 条序列")
    elif a.cmd == "calendar":
        runner.load_calendar(a.file, replace=a.replace, db=a.db)
    elif a.cmd == "package":
        runner.package(a.end, force=a.force, db=a.db, pkg_root=a.out_dir)
    elif a.cmd == "verify":
        problems = runner.verify(a.package)
        print("通过" if not problems else "\n".join(problems))
        return 1 if problems else 0
    elif a.cmd == "compare":
        print(json.dumps(runner.compare(a.ref, a.code, adj=a.adj, db=a.db, out=a.out), ensure_ascii=False, indent=1))
    elif a.cmd == "offline-restore":
        from .offline_restore import RestoreError, restore
        try:
            report = restore(a.db, a.recorded_dir, a.source_run_id, apply=a.apply)
        except (RestoreError, DB.DbError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=1))
    elif a.cmd == "preflight":
        from .quality import preflight
        try:
            report = preflight(a.db, a.end, start=a.start)
        except (DB.DbError, ValueError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report["research_ready"] else 1
    elif a.cmd == "upgrade-date-constraints":
        from .date_constraints import UpgradeError, upgrade
        try:
            report = upgrade(a.db, apply=a.apply)
        except UpgradeError as exc:
            print(json.dumps({**exc.report, "error": str(exc)}, ensure_ascii=False, indent=1), file=sys.stderr)
            return 1
        except (DB.DbError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
