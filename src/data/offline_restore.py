"""从 requests 锚定的 CSI 原响应离线恢复 H00300；默认只读，不导入网络执行路径。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import db as DB
from .sources import CSI_PERF, parse_csindex_data

CODE = "H00300"
THEME = "T01"
START = date(2000, 1, 1)
VALUES = ("open", "high", "low", "close", "volume", "amount")
BAR_COLUMNS = ("code", "adj", "date", *VALUES, "source", "fetched_at")


class RestoreError(ValueError):
    """证据、序列或 coverage 存在冲突；整个恢复事务拒绝写入。"""


def _day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise RestoreError(f"请求日期格式错误：{value!r}")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError as e:
        raise RestoreError(f"请求日期非法：{value!r}") from e


def _windows(end: date) -> list[tuple[date, date]]:
    return [(date(y, 1, 1), min(date(y, 12, 31), end)) for y in range(START.year, end.year + 1)]


def _requests(con, source_run_id: int, end: date, recorded_dir: Path):
    """所有目标响应都校验哈希，包括明确排除的候选探测短窗。"""
    expected = set(_windows(end))
    annual, short, evidence = {}, [], []
    root = recorded_dir.resolve(strict=True)
    if not root.is_dir():
        raise RestoreError(f"recorded 不是目录：{root}")
    for row in con.execute("SELECT * FROM requests WHERE run_id = ? ORDER BY seq", (source_run_id,)):
        entry = dict(row)
        parts = urlsplit(entry["url"])
        query = parse_qs(parts.query, keep_blank_values=True)
        if CODE not in query.get("indexCode", []):
            continue
        if (f"{parts.scheme}://{parts.netloc}{parts.path}" != CSI_PERF or parts.fragment
                or set(query) != {"indexCode", "startDate", "endDate"}
                or any(len(v) != 1 for v in query.values())):
            raise RestoreError(f"request {row['seq']} 不是唯一确定的 H00300 CSI 请求")
        b, e = _day(query["startDate"][0]), _day(query["endDate"][0])
        if b > e:
            raise RestoreError(f"request {row['seq']} 日期倒置")
        window = (b, e)
        is_annual = window in expected
        if not is_annual and window != (end - timedelta(days=45), end):
            raise RestoreError(f"request {row['seq']} 既不是完整年度窗口也不是 45 天候选短窗")
        if row["error"]:
            raise RestoreError(f"request {row['seq']} 记录了请求错误，不能恢复")
        filename = row["file"]
        if not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
            raise RestoreError(f"request {row['seq']} 缺少安全的原响应相对路径")
        path = (root / filename).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise RestoreError(f"request {row['seq']} 原响应不在 recorded 目录内")
        raw = path.read_bytes()
        if (not isinstance(row["bytes"], int) or row["bytes"] != len(raw)
                or not isinstance(row["sha256"], str)
                or hashlib.sha256(raw).hexdigest() != row["sha256"].lower()):
            raise RestoreError(f"request {row['seq']} bytes / sha256 校验失败")
        try:
            fetched = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
            if fetched.utcoffset() is None:
                raise ValueError("时刻缺少时区")
        except (ValueError, TypeError, AttributeError) as ex:
            raise RestoreError(f"request {row['seq']} fetched_at 非法") from ex
        evidence.append(entry)
        if is_annual:
            if window in annual:
                raise RestoreError(f"年度 {b.year} 请求重复，拒绝猜测选用哪次响应")
            annual[window] = (entry, raw)
        else:
            short.append(row["seq"])
    missing = sorted(expected - annual.keys())
    if missing:
        raise RestoreError("年度请求缺失：" + ", ".join(str(b.year) for b, _ in missing))
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode()).hexdigest()
    return annual, short, evidence, digest


def _parse(annual):
    rows, name, warnings = [], None, []
    for (b, e), (request, raw) in sorted(annual.items()):
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise RestoreError(f"request {request['seq']} 原响应不是 UTF-8 JSON") from ex
        if not isinstance(payload, dict):
            raise RestoreError(f"request {request['seq']} CSI 响应不是对象")
        if str(payload.get("code")) != "200":
            if rows or payload.get("data"):
                raise RestoreError(f"request {request['seq']} CSI 业务错误，不能恢复")
            warnings.append(f"{b.year}: CSI code={payload.get('code')}，起点可能被截短")
            continue
        data = payload.get("data")
        if data is None:
            data = []
        if not isinstance(data, list):
            raise RestoreError(f"request {request['seq']} data 不是数组")
        for item in data:
            if not isinstance(item, dict):
                raise RestoreError(f"request {request['seq']} 包含非对象行情")
            d = _day(item.get("tradeDate"))
            if not b <= d <= e:
                raise RestoreError(f"request {request['seq']} 包含年度窗口外日期 {d}")
            if item.get("indexCode") not in (None, "", CODE):
                raise RestoreError(f"request {request['seq']} 响应指数不是 H00300")
        parsed = parse_csindex_data(data, preserve_null_close=True)
        name = name or parsed.name
        for row in parsed.rows:
            if any(v is not None and not math.isfinite(v) for v in (row[k] for k in VALUES)):
                raise RestoreError(f"request {request['seq']} 含非有限行情数值")
            rows.append(dict(code=CODE, adj="raw", **row, source="csi", fetched_at=request["fetched_at"]))
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise RestoreError("年度响应没有 H00300 行情")
    if len({row["date"] for row in rows}) != len(rows):
        raise RestoreError("年度响应含重复日期，拒绝静默去重")
    return rows, name, warnings


def _coverage(base, rows, name):
    cov = {key: base[key] for key in DB.COVERAGE_COLUMNS}
    gap = max(((date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days
               for a, b in zip(rows, rows[1:])), default=0)
    cov.update(route_used="csi", series_code=CODE, series_adj="raw", series_name=name or "",
               first_date=rows[0]["date"], last_date=rows[-1]["date"], rows=str(len(rows)),
               tr_code_used=CODE, price_only="False", error="", max_gap_days=str(gap),
               ohlc_missing_rows=str(sum(any(r[k] is None or r[k] <= 0 for k in ("open", "high", "low")) for r in rows)),
               volume_missing_rows=str(sum(r["volume"] is None or r["volume"] <= 0 for r in rows)))
    return cov


def restore(db: Path, recorded_dir: Path, source_run_id: int, *, apply: bool = False) -> dict:
    """验证指定 run 的全部 H00300 响应；显式 apply 才以单事务恢复行情与 T01 研究 coverage。

    只接受年度窗口全集和已知 45 天候选短窗。短窗校验后排除，不补齐缺失收盘，不滤非交易日。
    现有 H00300 行必须是恢复结果的精确子集（含获取时刻）；其余表与历史行仅查询、不覆写。
    """
    DB.refuse_default_in_tests(db, DB.MARKET_DB)
    path = Path(db).resolve()
    if not path.is_file():
        raise RestoreError(f"行情库不存在：{path}")
    con = sqlite3.connect(path.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        version = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if version is None or version[0] != DB.SCHEMA_VERSION:
            raise RestoreError("行情库 schema 不符；离线恢复不创建或迁移 schema")
        if apply:
            DB.require_date_constraints(con)
        run = con.execute("SELECT * FROM runs WHERE run_id = ?", (source_run_id,)).fetchone()
        if run is None or run["kind"] not in ("probe", "backfill"):
            raise RestoreError("source_run_id 必须指向原 probe / backfill 作业")
        if run["status"] != "ok":
            raise RestoreError("原作业尚未成功结束，不能作为完整恢复证据")
        try:
            source_args = json.loads(run["args"] or "{}")
        except json.JSONDecodeError as ex:
            raise RestoreError("原作业 args 不是有效 JSON") from ex
        if not isinstance(source_args, dict) or source_args.get("start") != START.isoformat():
            raise RestoreError("原作业必须声明 start=2000-01-01，不缩短恢复窗口")
        try:
            end = date.fromisoformat(run["end_date"])
        except (TypeError, ValueError) as ex:
            raise RestoreError("原作业缺少有效 end_date") from ex
        if end < START:
            raise RestoreError("原作业 end_date 早于 2000-01-01")
        annual, short, evidence, digest = _requests(con, source_run_id, end, Path(recorded_dir))
        rows, name, warnings = _parse(annual)
        base = con.execute("SELECT * FROM coverage_latest WHERE theme_id = ?", (THEME,)).fetchone()
        if base is None:
            raise RestoreError("缺少现有 T01 coverage，无法保留执行 coverage")
        if con.execute("SELECT 1 FROM coverage_latest WHERE exec_code = ? LIMIT 1", (CODE,)).fetchone():
            raise RestoreError("H00300 被执行 coverage 引用，拒绝改动执行行情")
        desired = {r["date"]: r for r in rows}
        existing = {r["date"]: dict(r) for r in con.execute("SELECT * FROM bars WHERE code = ? AND adj = 'raw'", (CODE,))}
        for day, old in existing.items():
            if day not in desired or old != desired[day]:
                raise RestoreError(f"已有 H00300/{day} 与离线证据冲突（含来源 / 获取时刻），拒绝覆盖")
        added = [r for r in rows if r["date"] not in existing]
        cov = _coverage(base, rows, name)
        previous_run = None
        for r in con.execute("SELECT run_id, args FROM runs WHERE kind = 'backfill' AND status = 'ok' ORDER BY run_id DESC"):
            try:
                args = json.loads(r["args"] or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(args, dict) and args.get("offline_restore") is True and args.get("manifest_sha256") == digest:
                previous_run = r["run_id"]
                break
        needs_write = bool(added or previous_run is None or any(cov[k] != base[k] for k in DB.COVERAGE_COLUMNS))
        result = {"operation": "offline_restore", "dry_run": not apply, "applied": False,
                  "changed": False, "would_change": needs_write, "idempotent": not needs_write,
                  "source_run_id": source_run_id, "run_id": previous_run, "manifest_sha256": digest,
                  "verified_requests": len(evidence), "annual_requests": len(annual),
                  "excluded_short_window_requests": short, "rows": len(rows), "rows_to_insert": len(added),
                  "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
                  "ohlc_missing_rows": int(cov["ohlc_missing_rows"]),
                  "null_close_rows": sum(r["close"] is None for r in rows), "warnings": warnings}
        if not apply or not needs_write:
            con.rollback()
            return result
        at = DB.now()
        marker = f"offline_restore H00300 source_run_id={source_run_id} manifest_sha256={digest}"
        cov["notes"] = base["notes"] if marker in base["notes"] else " | ".join(filter(None, [base["notes"], marker, *warnings]))
        cov["checked_at"] = at
        args = {"offline_restore": True, "source_run_id": source_run_id, "manifest_sha256": digest,
                "start": START.isoformat(), "end": end.isoformat(), "code": CODE, "theme_id": THEME,
                "annual_request_seqs": [entry["seq"] for entry, _ in annual.values()],
                "excluded_short_window_request_seqs": short,
                "request_refs": [{"run_id": source_run_id, "seq": e["seq"], "sha256": e["sha256"]} for e in evidence]}
        cur = con.execute("INSERT INTO runs (kind, started_at, finished_at, end_date, args, git_commit, universe_sha256, status) "
                          "VALUES ('backfill', ?, ?, ?, ?, ?, ?, 'ok')",
                          (at, at, end.isoformat(), json.dumps(args, ensure_ascii=False), DB.git_head(), run["universe_sha256"]))
        run_id = cur.lastrowid
        con.executemany(f"INSERT INTO bars ({', '.join(BAR_COLUMNS)}) VALUES ({', '.join('?' for _ in BAR_COLUMNS)})",
                        [tuple(r[k] for k in BAR_COLUMNS) for r in added])
        con.execute(f"INSERT INTO coverage (run_id, {', '.join(DB.COVERAGE_COLUMNS)}) "
                    f"VALUES (?, {', '.join('?' for _ in DB.COVERAGE_COLUMNS)})",
                    (run_id, *(cov[k] for k in DB.COVERAGE_COLUMNS)))
        con.commit()
        result.update(applied=True, changed=True, run_id=run_id)
        return result
    except (OSError, sqlite3.DatabaseError) as ex:
        con.rollback()
        raise RestoreError(f"离线恢复失败，未写入：{ex}") from ex
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
