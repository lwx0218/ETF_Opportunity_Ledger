"""data/raw/<code>[.hfq].csv 的读写与合并。一个文件 = 一条序列，只来自一个路由（source 列），
增量更新时换了路由就拒绝合并——不同源（例如布伦特现货与期货）不能拼成一条序列。"""
from __future__ import annotations

import csv
import re
from pathlib import Path

COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "source"]


class MixError(ValueError):
    pass


def file_name(code: str, route: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", code.lstrip("^"))
    return f"{safe}.hfq.csv" if route == "eastmoney_etf_hfq" else f"{safe}.csv"


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return str(v)


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["date"]):
            w.writerow({k: _fmt(r.get(k)) for k in COLUMNS})
    tmp.replace(path)


def source_of(rows: list[dict]) -> str | None:
    srcs = {r.get("source") for r in rows if r.get("source")}
    if len(srcs) > 1:
        raise MixError(f"文件内混有多个来源：{sorted(srcs)}")
    return next(iter(srcs), None)


def merge(old: list[dict], new: list[dict], route: str) -> tuple[list[dict], int, int]:
    """新行覆盖同日旧行。返回 (合并后, 新增日数, 被修正日数)。"""
    prev = source_of(old)
    if prev and prev != route:
        raise MixError(f"已有序列来自 {prev}，本次来自 {route}，拒绝拼接")
    by = {r["date"]: dict(r) for r in old}
    added = revised = 0
    for r in new:
        r = {**{k: _fmt(r.get(k)) for k in COLUMNS[:-1]}, "source": route}
        cur = by.get(r["date"])
        if cur is None:
            added += 1
        elif any(_num(cur.get(k)) != _num(r.get(k)) for k in ("open", "high", "low", "close")):
            revised += 1
        by[r["date"]] = r
    return [by[d] for d in sorted(by)], added, revised


def _num(x):
    try:
        return round(float(x), 6)
    except (TypeError, ValueError):
        return None
