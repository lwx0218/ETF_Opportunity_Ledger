"""从腾讯不复权与 qfq 的收盘差推导现金分红。qfq 不入库。

腾讯 qfq 是减法复权：diff(t) = 不复权收盘 − qfq 收盘 = 除息日晚于 t 的现金分红之和。
相邻两个都有两边收盘的交易日，diff 下降的幅度就是这一天的每股现金分红。
后来的分红会把更早的 diff 两边一起抬高，阶跃大小不变，所以重复推导是幂等的。
同一代码、同一除息日只保留第一次写入。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from src.data import db as DB
from src.data import http
from src.data import store
from src.data import universe as U
from src.data.sources import fetch_tencent

# 与 compare() 的 tol 相同：1.5 个最小价位。更小的阶跃是四舍五入，不是分红。
STEP_TOL = 0.0015
# A 股 ETF 单日涨跌幅限制多数 ±10%，创业板、科创板相关 ±20%。
# 阈值高于这个上限，限制以内的跳空走正常止损。
# 25% 仍会把回放里黄金次日开盘 200、前收 308（约 −35%）判成份额折算，
# 作废理由从「开盘已在失效位下方」变成「数据断档」。取 40%，高于 20% 限制，也高于这次构造。
GAP_LIMIT = 0.40

_TABLE = """
CREATE TABLE IF NOT EXISTS cash_dividends (
    code        TEXT NOT NULL,
    ex_date     TEXT NOT NULL CHECK (date(ex_date) = ex_date),
    amount      REAL NOT NULL CHECK (amount > 0),
    prev_close  REAL NOT NULL CHECK (prev_close > amount),
    run_id      INTEGER NOT NULL,
    request_seq INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (code, ex_date)
) WITHOUT ROWID
"""
_NO_UPDATE = """
CREATE TRIGGER IF NOT EXISTS cash_dividends_no_update BEFORE UPDATE ON cash_dividends
BEGIN
    SELECT RAISE(ABORT, 'cash_dividends 只追加');
END
"""
_NO_DELETE = """
CREATE TRIGGER IF NOT EXISTS cash_dividends_no_delete BEFORE DELETE ON cash_dividends
BEGIN
    SELECT RAISE(ABORT, 'cash_dividends 只追加');
END
"""


def ensure(con) -> None:
    con.execute(_TABLE)
    con.execute(_NO_UPDATE)
    con.execute(_NO_DELETE)


def derive_cash_dividends(raw_rows: list[dict], qfq_rows: list[dict]) -> list[dict]:
    """返回 [{ex_date, amount, prev_close}]。只认相邻交易日上的向下阶跃。"""
    raw = {r["date"]: r for r in raw_rows if r.get("date") and r.get("close") is not None}
    qfq = {r["date"]: r["close"] for r in qfq_rows if r.get("date") and r.get("close") is not None}
    days = [d for d in sorted(raw) if d in qfq]
    out, prev = [], None
    for d in days:
        diff = float(raw[d]["close"]) - float(qfq[d])
        if prev is not None:
            step = prev["diff"] - diff
            if step > STEP_TOL and prev["close"] > step:
                out.append({"ex_date": d, "amount": round(step, 6), "prev_close": prev["close"]})
        prev = {"date": d, "diff": diff, "close": float(raw[d]["close"])}
    return out


def _record(con, run_id: int, seq: int, code: str, items: list[dict], now: str) -> int:
    wrote = 0
    with con:
        for item in items:
            cur = con.execute(
                """INSERT OR IGNORE INTO cash_dividends
                   (code, ex_date, amount, prev_close, run_id, request_seq, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (code, item["ex_date"], item["amount"], item["prev_close"], run_id, seq, now))
            wrote += cur.rowcount
    return wrote


def sync_qfq(con, run_id: int, windows: dict, end: date, *, log=print) -> None:
    """为给出的代码再拉一次 qfq。失败只记日志，不让这次 mvp 更新失败。"""
    if not windows:
        return
    ensure(con)
    own_record = http.RECORD_DIR is None
    if own_record:
        http.RECORD_DIR = DB.ROOT / "outputs" / "data" / "dividends"
    try:
        for code, start in sorted(windows.items()):
            sym = U.fund_tencent(code)
            if not sym:
                log(f"  qfq {code}: 没有腾讯代码，跳过")
                continue
            before = len(http.LOG)
            try:
                got = fetch_tencent(sym, start, end, adjust="qfq")
            except Exception as exc:  # noqa: BLE001 — 分红取数失败不阻断行情更新
                log(f"  qfq {code}: {str(exc)[:120]}")
                continue
            seq = len(http.LOG) - 1
            if seq < before or not got.rows:
                log(f"  qfq {code}: 没有前复权收盘，不推导分红")
                continue
            raw = [r for r in store.read(con, code, "raw") if r.get("date") and r["date"] >= start.isoformat()]
            items = derive_cash_dividends(raw, got.rows)
            wrote = _record(con, run_id, seq, code, items, DB.now())
            log(f"  qfq {code}: 推导 {len(items)} 笔现金分红，新写入 {wrote} 笔")
    finally:
        if own_record:
            http.RECORD_DIR = None


def load_dividends(db, codes) -> dict[str, list[dict]]:
    """只读。表还不存在时返回空，调用方按不复权价继续。"""
    wanted = [c for c in dict.fromkeys(codes or []) if c]
    if not wanted or not Path(db).exists():
        return {}
    con = DB.connect(db, readonly=True)
    try:
        have = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cash_dividends'").fetchone()
        if not have:
            return {}
        marks = ",".join("?" * len(wanted))
        out: dict[str, list[dict]] = {}
        for row in con.execute(
                f"""SELECT code, ex_date, amount, prev_close FROM cash_dividends
                    WHERE code IN ({marks}) ORDER BY code, ex_date""", tuple(wanted)):
            out.setdefault(row["code"], []).append(
                {"ex_date": row["ex_date"], "amount": row["amount"], "prev_close": row["prev_close"]})
        return out
    finally:
        con.close()
