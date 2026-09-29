"""python -m src.ledger init|summary [--db data/ledger.sqlite]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .store import DEFAULT_DB, Ledger


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ledger", description="机会卡片台账")
    ap.add_argument("cmd", choices=["init", "summary"], help="init：建库并同步固定源清单；summary：分母与分档统计")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    a = ap.parse_args(argv)
    L = Ledger(a.db)
    try:
        if a.cmd == "init":
            n = L.conn.execute("SELECT count(*), sum(grade IN ('A','B')) FROM fixed_sources").fetchone()
            print(f"{a.db}：固定源 {n[0]} 个，可进卡片（A/B）{n[1]} 个")
        else:
            print(json.dumps({"summary": L.summary(), "calibration_agent": L.calibration("agent"),
                              "calibration_owner": L.calibration("owner")}, ensure_ascii=False, indent=1))
    finally:
        L.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
