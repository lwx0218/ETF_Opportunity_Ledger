"""data/market.sqlite 的 bars 表：序列的读写与合并（replan §11）。一条序列 = (code, adj)，只来自一个路由（source 列）；
增量更新时换了路由就拒绝合并——不同源（例如布伦特现货与期货）不能拼成一条序列。库里的触发器 bars_one_source 再挡一次。
adj = hfq 只给后复权路由 eastmoney_etf_hfq，其余（指数点位、不复权执行价）都是 raw。"""
from __future__ import annotations

import math

COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "source"]
VALUES = COLUMNS[1:-1]
HFQ_ROUTE = "eastmoney_etf_hfq"


class MixError(ValueError):
    pass


def adj_of(route: str) -> str:
    return "hfq" if route == HFQ_ROUTE else "raw"


def _val(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def read(con, code: str, adj: str) -> list[dict]:
    """整条序列，按日期升序；数值为 float 或 None。"""
    cur = con.execute(f"SELECT {', '.join(COLUMNS)} FROM bars WHERE code = ? AND adj = ? ORDER BY date", (code, adj))
    return [dict(zip(COLUMNS, r)) for r in cur]


def span(con, code: str, adj: str) -> dict:
    """序列的起止日期、行数与来源（没有行时 rows = 0）。"""
    r = con.execute("SELECT min(date), max(date), count(*), min(source), count(DISTINCT source) FROM bars WHERE code = ? AND adj = ?",
                    (code, adj)).fetchone()
    return {"first": r[0], "last": r[1], "rows": r[2], "source": r[3], "sources": r[4]}


def source_of(rows: list[dict]) -> str | None:
    srcs = {r.get("source") for r in rows if r.get("source")}
    if len(srcs) > 1:
        raise MixError(f"序列内混有多个来源：{sorted(srcs)}")
    return next(iter(srcs), None)


def merge(old: list[dict], new: list[dict], route: str) -> tuple[list[dict], int, int]:
    """新行覆盖同日旧行。返回 (合并后, 新增日数, 被修正日数)。"""
    prev = source_of(old)
    if prev and prev != route:
        raise MixError(f"已有序列来自 {prev}，本次来自 {route}，拒绝拼接")
    by = {r["date"]: dict(r) for r in old}
    added = revised = 0
    for r in new:
        r = {"date": r["date"], **{k: _val(r.get(k)) for k in VALUES}, "source": route}
        cur = by.get(r["date"])
        if cur is None:
            added += 1
        elif any(_num(cur.get(k)) != _num(r.get(k)) for k in ("open", "high", "low", "close")):
            revised += 1
        by[r["date"]] = r
    return [by[d] for d in sorted(by)], added, revised


def _rows(code: str, route: str, rows: list[dict], fetched_at: str) -> list[tuple]:
    adj = adj_of(route)
    return [(code, adj, r["date"], *[_val(r.get(k)) for k in VALUES], route, fetched_at) for r in rows]


_INSERT = "INSERT INTO bars (code, adj, date, open, high, low, close, volume, amount, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"


def replace(con, code: str, route: str, rows: list[dict], fetched_at: str) -> None:
    """整条序列换成 rows（backfill 全量）：先删后插，同一事务。"""
    with con:
        con.execute("DELETE FROM bars WHERE code = ? AND adj = ?", (code, adj_of(route)))
        con.executemany(_INSERT, _rows(code, route, rows, fetched_at))


def upsert(con, code: str, route: str, rows: list[dict], fetched_at: str) -> None:
    """按日期覆盖或新增（update 增量）；同日旧行被本次抓到的行替换，其余旧行不动。"""
    with con:
        con.executemany(_INSERT.replace("INSERT", "INSERT OR REPLACE", 1), _rows(code, route, rows, fetched_at))


def _num(x):
    try:
        return round(float(x), 6)
    except (TypeError, ValueError):
        return None
