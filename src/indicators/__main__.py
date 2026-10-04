"""python -m src.indicators build --package <研究数据包.sqlite> [--out panel-D.sqlite]
python -m src.indicators legacy-check [--data data/]     与 09-25 快照的 data/panel_daily.csv 逐日比对"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import date

from .build import ROOT, build, legacy_check


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.indicators", description="指标层：研究数据包 → V1 长表（库）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--start", type=date.fromisoformat, default=None, help="请求窗口起点；省略时使用官方日历首日")
    p = sub.add_parser("legacy-check")
    p.add_argument("--data", type=Path, default=ROOT / "data")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build(a.package, a.out, start=a.start)
    else:
        res = legacy_check(a.data)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 1 if any(v["state_diff"] or v["ext_diff"] or v["rs_1m_diff"] for v in res.values()) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
