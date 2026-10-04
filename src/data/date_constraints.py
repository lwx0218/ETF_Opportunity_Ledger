"""market-v1 日期约束：显式升级只追加触发器，不重建表、不改历史行。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DATE_CONSTRAINT_KEY = "date_constraints"
DATE_CONSTRAINT_VERSION = "gregorian-v1"


def valid_date_sql(value: str) -> str:
    """固定 SQL 标识符用；不依赖 SQLite date() 对不存在日期的宽松解析。"""
    year = f"CAST(substr({value}, 1, 4) AS INTEGER)"
    month = f"CAST(substr({value}, 6, 2) AS INTEGER)"
    day = f"CAST(substr({value}, 9, 2) AS INTEGER)"
    return f"""(typeof({value}) = 'text'
        AND length(CAST({value} AS BLOB)) = 10
        AND {value} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        AND {year} BETWEEN 1 AND 9999
        AND {month} BETWEEN 1 AND 12
        AND {day} BETWEEN 1 AND CASE
            WHEN {month} = 2 THEN 28 + ({year} % 4 = 0 AND ({year} % 100 != 0 OR {year} % 400 = 0))
            WHEN {month} IN (4, 6, 9, 11) THEN 30 ELSE 31 END) IS 1"""


def date_rule(table: str, value: str) -> str:
    rule = valid_date_sql(value)
    if table == "runs":
        return f"({value} IS NULL OR ({rule}))"
    if table == "calendar":
        return f"(({rule}) AND strftime('%w', {value}) NOT IN ('0', '6')) IS 1"
    return rule


# 新库与升级库使用同一触发器合同，独立 sqlite3 连接也必须遵守。
DATE_COLUMNS = {"bars": ("date", ("code", "adj", "date")),
                "calendar": ("date", ("date",)), "runs": ("end_date", ("run_id",))}
DATE_TRIGGERS = {}
for _table, (_column, _) in DATE_COLUMNS.items():
    for _event in ("INSERT", "UPDATE"):
        _name = f"{_table}_date_{_event.lower()}"
        DATE_TRIGGERS[_name] = f"""CREATE TRIGGER {_name} BEFORE {_event} ON {_table}
WHEN NOT ({date_rule(_table, 'NEW.' + _column)})
BEGIN
    SELECT RAISE(ABORT, '{_table}.{_column}: invalid Gregorian date');
END"""


def constraint_state(con) -> tuple[str | None, list[str]]:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (DATE_CONSTRAINT_KEY,)).fetchone()
    revision = row[0] if row else None
    present = dict(con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"))
    missing = []
    for name, sql in DATE_TRIGGERS.items():
        if name not in present:
            missing.append(name)
        elif present[name] != sql:
            from .db import DbError
            raise DbError(f"日期约束触发器 {name} 定义冲突；停止升级，不覆盖已有定义")
    return revision, missing


def require_date_constraints(con) -> None:
    from .db import DbError
    revision, missing = constraint_state(con)
    if revision != DATE_CONSTRAINT_VERSION or missing:
        raise DbError("日期约束未升级或不完整；请先运行 python -m src.data upgrade-date-constraints --db <库路径>，"
                      "检查报告后显式加 --apply；本入口不自动迁移")


def invalid_dates(con) -> list[dict]:
    """遍历三个字段的全部历史；repr 保留非法 BLOB / 内嵌 NUL 的诊断信息。"""
    problems = []
    for table, (column, keys) in DATE_COLUMNS.items():
        rows = con.execute(f"SELECT {', '.join(keys)}, {column} AS invalid_value FROM {table} "
                           f"WHERE NOT ({date_rule(table, column)}) ORDER BY {', '.join(keys)}")
        for row in rows:
            problems.append({"table": table, "column": column,
                             "key": {key: repr(row[key]) if isinstance(row[key], bytes) else row[key] for key in keys},
                             "value": repr(row["invalid_value"])})
    return problems


def upgrade(db: Path, *, apply: bool = False) -> dict:
    """默认只读审计；apply 原子新增数据库约束，非法历史或 DDL 冲突一律停止。"""
    from . import db as DB
    DB.refuse_default_in_tests(db, DB.MARKET_DB)
    path = Path(db).resolve()
    if not path.is_file():
        raise DB.DbError(f"行情库不存在：{path}")
    con = sqlite3.connect(path.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        version = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if version is None or version[0] != DB.SCHEMA_VERSION:
            raise DB.DbError("约束升级仅适用于现存 market-v1 库")
        revision, missing = constraint_state(con)
        if revision not in (None, DATE_CONSTRAINT_VERSION):
            raise DB.DbError(f"未知日期约束版本 {revision}；停止升级")
        problems = invalid_dates(con)
        needed = revision is None or bool(missing)
        report = {"operation": "upgrade_date_constraints", "dry_run": not apply,
                  "applied": False, "changed": False, "would_change": needed,
                  "idempotent": not needed, "from_revision": revision,
                  "to_revision": DATE_CONSTRAINT_VERSION,
                  "invalid_count": len(problems), "invalid_dates": problems}
        if problems:
            raise UpgradeError("发现存量非法日期，停止升级；历史数据未改写", report)
        if not apply or not needed:
            con.rollback()
            return report
        for name in missing:
            con.execute(DATE_TRIGGERS[name])  # executescript 会提前提交，不能用于升级事务。
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (DATE_CONSTRAINT_KEY, DATE_CONSTRAINT_VERSION))
        con.commit()
        report.update(applied=True, changed=True)
        return report
    except sqlite3.DatabaseError as exc:
        con.rollback()
        raise DB.DbError(f"日期约束升级失败，未写入：{exc}") from exc
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


class UpgradeError(RuntimeError):
    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report
