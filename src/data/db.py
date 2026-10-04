"""data/market.sqlite：行情、coverage、请求记录、作业、交易日历、universe、meta 放一个库（replan §11，参照 serenity physical-first）。

- 标准库 sqlite3，schema 写在代码里；`journal_mode = DELETE`，库文件入 Git，提交前不留 -wal / -shm。
- bars 主键 (code, adj, date)：adj = hfq 只给后复权路由（eastmoney_etf_hfq），其余 raw（指数点位、不复权执行价）。
  一条序列 (code, adj) 只来自一个路由——换了路由就拒绝拼接（触发器），与 CSV 时代「一个文件一个来源」同一条规则。
- coverage 每次作业写一批（带 run_id），保留历史；当前口径 = 每个 theme_id 最近一次作业那一行。
- 测试只许连临时库：环境变量 ETF_LEDGER_TESTING 置位时（tests/__init__.py 设置），连默认库路径一律拒绝。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .date_constraints import (DATE_CONSTRAINT_KEY, DATE_CONSTRAINT_VERSION, DATE_TRIGGERS,
                               date_rule, require_date_constraints)

ROOT = Path(__file__).resolve().parents[2]
MARKET_DB = ROOT / "data" / "market.sqlite"
SCHEMA_VERSION = "market-v1"
TESTING_ENV = "ETF_LEDGER_TESTING"

COVERAGE_COLUMNS = [
    "container", "code", "route_used", "first_date", "last_date", "rows", "tr_code_used", "price_only", "error",
    "theme_id", "status", "series_code", "series_adj", "series_name",
    "max_gap_days", "price_first_date", "ohlc_missing_rows", "volume_missing_rows",
    "exec_code", "exec_route", "exec_first_date", "exec_last_date", "exec_rows", "exec_error", "checked_at", "notes",
]
RUN_KINDS = ("probe", "backfill", "update", "package", "calendar")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN {RUN_KINDS}),
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    end_date        TEXT CHECK ({date_rule('runs', 'end_date')}),
    args            TEXT,
    git_commit      TEXT,
    universe_sha256 TEXT,
    status          TEXT
);

CREATE TABLE IF NOT EXISTS bars (
    code       TEXT NOT NULL CHECK (length(code) > 0),
    adj        TEXT NOT NULL CHECK (adj IN ('raw', 'hfq')),
    date       TEXT NOT NULL CHECK ({date_rule('bars', 'date')}),
    open       REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
    source     TEXT NOT NULL CHECK (length(source) > 0),
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (code, adj, date),
    CHECK ((adj = 'hfq') = (source = 'eastmoney_etf_hfq'))
) WITHOUT ROWID;

CREATE TRIGGER IF NOT EXISTS bars_one_source BEFORE INSERT ON bars
BEGIN
    -- 同一序列的行来源一致（本触发器保证），看任意一行即可：走主键前缀，O(log n)
    SELECT RAISE(ABORT, '一条序列只来自一个路由：已有序列来自别的来源，拒绝拼接')
     WHERE (SELECT source FROM bars WHERE code = NEW.code AND adj = NEW.adj LIMIT 1) <> NEW.source;
END;

-- 行情只整行写入（backfill 先删后插、update 按日 INSERT OR REPLACE）：UPDATE 一律拒绝，免得绕过上面那条把来源改混
CREATE TRIGGER IF NOT EXISTS bars_no_update BEFORE UPDATE ON bars
BEGIN
    SELECT RAISE(ABORT, 'bars 不允许 UPDATE：整行重写（同一来源）');
END;

CREATE TABLE IF NOT EXISTS coverage (
    run_id   INTEGER NOT NULL REFERENCES runs(run_id),
    theme_id TEXT NOT NULL,
    {", ".join(f"{c} TEXT NOT NULL DEFAULT ''" for c in COVERAGE_COLUMNS if c != "theme_id")},
    PRIMARY KEY (run_id, theme_id)
);

CREATE TABLE IF NOT EXISTS requests (
    run_id     INTEGER NOT NULL REFERENCES runs(run_id),
    seq        INTEGER NOT NULL,
    url        TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    bytes      INTEGER,
    sha256     TEXT,
    error      TEXT,
    file       TEXT,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS update_results (
    run_id    INTEGER NOT NULL REFERENCES runs(run_id),
    seq       INTEGER NOT NULL,
    theme_id  TEXT NOT NULL,
    kind      TEXT NOT NULL,
    code      TEXT NOT NULL,
    adj       TEXT NOT NULL,
    route     TEXT,
    ok        INTEGER NOT NULL CHECK (ok IN (0, 1)),
    since     TEXT, added INTEGER, revised INTEGER, last_date TEXT, error TEXT,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS calendar (
    date TEXT PRIMARY KEY CHECK ({date_rule('calendar', 'date')})
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS universe (
    ord      INTEGER NOT NULL,
    theme_id TEXT PRIMARY KEY,
    row      TEXT NOT NULL
) WITHOUT ROWID;

CREATE VIEW IF NOT EXISTS coverage_latest AS
SELECT c.* FROM coverage c
 WHERE c.run_id = (SELECT max(run_id) FROM coverage x WHERE x.theme_id = c.theme_id);
""" + ";\n".join(DATE_TRIGGERS.values()) + ";\n"

PACKAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS package (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
"""


class DbError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def refuse_default_in_tests(path, default: Path) -> None:
    """测试只许连临时库（serenity 的硬防线）：ETF_LEDGER_TESTING 置位时，默认库路径一律拒绝。"""
    if os.environ.get(TESTING_ENV) and str(path) != ":memory:" and Path(path).resolve() == Path(default).resolve():
        raise DbError(f"测试只许连临时库，拒绝默认库 {default}")


def _check_schema(con, path) -> bool:
    """先查版本再建表：旧库不能被 IF NOT EXISTS 补上半套新表。"""
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not have:
        return False
    v = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone() if "meta" in have else None
    if v is None or v[0] != SCHEMA_VERSION:
        con.close()
        raise DbError(f"{path} 的 schema 是 {v[0] if v else '未知'}，当前代码是 {SCHEMA_VERSION}；需迁移")
    return True


def connect(path=MARKET_DB, *, readonly: bool = False, schema: str = SCHEMA) -> sqlite3.Connection:
    """readonly=True：只读打开（package / verify / build / 每日任务现算面板），文件不存在或 schema 不对即报错。"""
    refuse_default_in_tests(path, MARKET_DB)
    if readonly:
        if not Path(path).exists():
            raise DbError(f"{path} 不存在")
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    existing = _check_schema(con, path)
    if readonly:
        return con
    if existing:
        try:
            require_date_constraints(con)
        except BaseException:
            con.close()
            raise
    con.execute("PRAGMA journal_mode = DELETE")                   # 入 Git 的库不留 -wal / -shm
    if not existing:
        con.executescript(schema)
        con.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                        [("schema", SCHEMA_VERSION), (DATE_CONSTRAINT_KEY, DATE_CONSTRAINT_VERSION)])
        con.commit()
    return con


def git_head() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 — 不在 Git 工作区（例如解压的包）时记空
        return None


def git_clean(path: Path) -> bool | None:
    """path 与 HEAD 里的版本是否一致（未跟踪或有改动 = False）；不在 Git 工作区时 None。
    数据包记下它：源库 commit 只有在库文件与该 commit 一致时才能指认数据。"""
    try:
        rel = Path(path).resolve().relative_to(ROOT)
    except ValueError:
        return None
    try:
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", str(rel)], capture_output=True).returncode == 0
        if not tracked:
            return False
        return subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", str(rel)], capture_output=True).returncode == 0
    except Exception:  # noqa: BLE001
        return None


def content_sha256(con, tables: dict[str, str]) -> str:
    """库内容的规范化哈希：按 {表: 排序列} 逐表逐行序列化（JSON，浮点按 repr 往返）后求 sha256。
    与文件字节无关（SQLite 版本、页面布局、作业时刻都不影响），同一份数据在任何机器上算出同一个值——prereg §13 记它。"""
    h = hashlib.sha256()
    for table, order in tables.items():
        cur = con.execute(f"SELECT * FROM {table} ORDER BY {order}")
        cols = [d[0] for d in cur.description]
        h.update(json.dumps([table, cols], ensure_ascii=False).encode())
        for row in cur:
            h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
            h.update(b"\n")
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ 作业
def start_run(con, kind: str, *, end=None, args: dict | None = None, universe_sha256: str | None = None) -> int:
    cur = con.execute("INSERT INTO runs (kind, started_at, end_date, args, git_commit, universe_sha256, status) "
                      "VALUES (?, ?, ?, ?, ?, ?, 'running')",
                      (kind, now(), end.isoformat() if end else None, json.dumps(args or {}, ensure_ascii=False, default=str),
                       git_head(), universe_sha256))
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id: int, status: str = "ok") -> None:
    con.execute("UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?", (now(), status, run_id))
    con.commit()


# ------------------------------------------------------------------ universe（seed CSV → 库）
def load_universe(con, rows: list[dict], sha: str) -> None:
    with con:
        con.execute("DELETE FROM universe")
        con.executemany("INSERT INTO universe (ord, theme_id, row) VALUES (?, ?, ?)",
                        [(i, r["theme_id"], json.dumps(r, ensure_ascii=False)) for i, r in enumerate(rows)])
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('universe_sha256', ?)", (sha,))


def universe_order(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT theme_id FROM universe ORDER BY ord")]


# ------------------------------------------------------------------ coverage
def write_coverage(con, run_id: int, rows: list[dict]) -> None:
    cols = COVERAGE_COLUMNS
    with con:
        con.executemany(f"INSERT OR REPLACE INTO coverage (run_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                        [(run_id, *[str(r.get(c, "") if r.get(c) is not None else "") for c in cols]) for r in rows])


def read_coverage(con, table: str = "coverage_latest") -> list[dict]:
    """当前 coverage（每个 theme_id 最近一次作业那一行），按 universe 顺序。"""
    order = {t: i for i, t in enumerate(universe_order(con))}
    rows = [{c: r[c] for c in COVERAGE_COLUMNS} for r in con.execute(f"SELECT * FROM {table}")]
    return sorted(rows, key=lambda r: (order.get(r["theme_id"], len(order)), r["theme_id"]))


def write_update_results(con, run_id: int, report: list[dict]) -> None:
    with con:
        con.executemany("INSERT INTO update_results (run_id, seq, theme_id, kind, code, adj, route, ok, since, added, revised, last_date, error) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(run_id, i, e["theme_id"], e["kind"], e["code"], e["adj"], e.get("route"), int(bool(e.get("ok"))), e.get("since"),
                          e.get("added"), e.get("revised"), e.get("last_date"), e.get("error")) for i, e in enumerate(report)])


def write_requests(con, run_id: int, log: list[dict]) -> None:
    with con:
        con.executemany("INSERT INTO requests (run_id, seq, url, fetched_at, bytes, sha256, error, file) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [(run_id, i, e.get("url"), e.get("fetched_at"), e.get("bytes"), e.get("sha256"), e.get("error"), e.get("file"))
                         for i, e in enumerate(log)])


# ------------------------------------------------------------------ 交易日历
def load_calendar(con, days) -> int:
    with con:
        con.executemany("INSERT OR IGNORE INTO calendar (date) VALUES (?)", [(d.isoformat()[:10],) for d in days])
    return con.execute("SELECT count(*) FROM calendar").fetchone()[0]
