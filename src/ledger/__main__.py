"""python -m src.ledger init|summary|migrate [--db data/ledger.sqlite]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .store import DEFAULT_DB, SCHEMA_VERSION, Ledger, LedgerError, migrate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ledger", description="机会卡片台账")
    ap.add_argument("cmd", choices=["init", "summary", "migrate"],
                    help="init：建库并同步固定源清单；summary：分母与分档统计；migrate：把 v1.1-i 库补上新表")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--replay", action="store_true", help="以回放时钟建库（不能指向正式库）")
    ap.add_argument("--clock", default=None, help="回放时钟 YYYY-MM-DDTHH:MM，须与 --replay 同用")
    a = ap.parse_args(argv)
    if a.clock and not a.replay:
        print("注入时钟只用于回放：请同时传 --replay，并使用单独的库", file=sys.stderr)
        return 2
    if a.cmd == "migrate":
        if a.replay or a.clock:
            print("migrate 不改时钟，请不要传 --replay / --clock", file=sys.stderr)
            return 2
        try:
            prev = migrate(a.db)
        except LedgerError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"{a.db}：schema {SCHEMA_VERSION}（原先 {prev}）")
        return 0
    clock = (lambda: a.clock) if a.clock else None
    try:
        L = Ledger(a.db, clock=clock, replay=a.replay)
    except Exception as exc:  # noqa: BLE001 — 正式库与时钟模式错误要留在命令行
        print(str(exc), file=sys.stderr)
        return 2
    try:
        if a.cmd == "init":
            n = L.conn.execute("SELECT count(*), sum(grade IN ('A','B')) FROM current_sources").fetchone()
            print(f"{a.db}：固定源 {n[0]} 个，可进卡片（A/B）{n[1]} 个")
        else:
            print(json.dumps({"summary": L.summary(), "calibration_agent": L.calibration("agent")},
                             ensure_ascii=False, indent=1))
    finally:
        L.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
