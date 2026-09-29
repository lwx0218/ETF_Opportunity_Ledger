"""python -m src.data <命令>

    probe    [--end D] [--start D] [--only T01,T02] [--record DIR]   → outputs/data/coverage.csv
    backfill --end 2026-09-30 [--start D] [--exec-start D] [--only …] → data/raw/*.csv + coverage
    update   [--end D] [--only …]                                     增量（往回多拉 10 天）
    package  --end 2026-09-30 [--force]                               → outputs/research-package-<end>/
    verify   <包目录>                                                  按 MANIFEST.sha256 复验
    compare  <参考.csv> <raw.csv> [--out diff.csv]                     重叠区间逐日比对收盘
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

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
    p = sub.add_parser("verify")
    p.add_argument("dir", type=Path)
    p = sub.add_parser("compare")
    p.add_argument("ref", type=Path)
    p.add_argument("raw", type=Path)
    p.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)

    if a.cmd == "probe":
        covs = runner.probe(a.end, start=a.start, only=a.only, record=a.record)
        panel = [c for c in covs if c["status"] in ("retained", "flagged")]
        print(f"面板容器 {len(panel)}：有路由 {sum(1 for c in panel if c['route_used'])}，"
              f"error {sum(1 for c in panel if c['error'])} → {runner.OUT_DIR / 'coverage.csv'}")
    elif a.cmd == "backfill":
        runner.backfill(a.end, start=a.start, exec_start=a.exec_start, only=a.only)
    elif a.cmd == "update":
        rep = runner.update(a.end, only=a.only)
        print(f"更新 {sum(1 for r in rep if r.get('ok'))} / {len(rep)} 个文件")
    elif a.cmd == "package":
        runner.package(a.end, force=a.force)
    elif a.cmd == "verify":
        problems = runner.verify(a.dir)
        print("通过" if not problems else "\n".join(problems))
        return 1 if problems else 0
    elif a.cmd == "compare":
        print(json.dumps(runner.compare(a.ref, a.raw, out=a.out), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
