"""仅补录 H00300 三个年末缺日；原响应随作业保存，供年度恢复离线重验。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import db as DB
from .offline_restore import BAR_COLUMNS, CODE, THEME, RestoreError, _coverage, _day
from .sources import CSI_PERF, parse_csindex_data

FORMAT = "h00300-year-end-v1"
TARGET_DATES = ("2008-12-31", "2009-12-31", "2010-12-31")
REQUEST_COLUMNS = ("url", "fetched_at", "bytes", "sha256", "error", "file")


def _json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RestoreError(f"证据 JSON 含重复字段 {key}")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise RestoreError(f"证据不是有效 JSON：{exc}") from exc


def _manifest(text):
    manifest = _json(text)
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "requests"}
            or manifest["format"] != FORMAT or not isinstance(manifest["requests"], list)
            or len(manifest["requests"]) != 3):
        raise RestoreError(f"清单须为 {FORMAT}，包含三个短窗 requests")
    entries = []
    for entry in manifest["requests"]:
        if (not isinstance(entry, dict) or set(entry) - set(REQUEST_COLUMNS)
                or set(REQUEST_COLUMNS) - {"error"} - set(entry)):
            raise RestoreError("清单请求字段须为 url / file / bytes / sha256 / fetched_at，error 可省略")
        filename = entry["file"]
        if (not isinstance(filename, str) or not filename or Path(filename).is_absolute()
                or ".." in Path(filename).parts):
            raise RestoreError("原响应必须使用录件目录内的安全相对路径")
        entries.append({key: entry.get(key) for key in REQUEST_COLUMNS})
    return entries


def _validate(manifest_text, response_texts):
    """外部录件与库内审计都走同一验证；邻近日期只保留在原文，不加入 bars。"""
    entries = _manifest(manifest_text)
    if (not isinstance(response_texts, list) or len(response_texts) != len(entries)
            or not all(isinstance(text, str) for text in response_texts)):
        raise RestoreError("缺少完整原响应审计文本")
    rows = {}
    for entry, text in zip(entries, response_texts):
        raw = text.encode("utf-8")
        if (entry["error"] not in (None, "") or type(entry["bytes"]) is not int
                or entry["bytes"] != len(raw) or not isinstance(entry["sha256"], str)
                or not re.fullmatch(r"[a-fA-F0-9]{64}", entry["sha256"])
                or hashlib.sha256(raw).hexdigest() != entry["sha256"].lower()):
            raise RestoreError("原响应请求错误或 bytes / sha256 校验失败")
        if not isinstance(entry["url"], str):
            raise RestoreError("请求 URL 非法")
        try:
            parts = urlsplit(entry["url"])
            query = parse_qs(parts.query, keep_blank_values=True)
        except ValueError as exc:
            raise RestoreError("请求 URL 非法") from exc
        if (f"{parts.scheme}://{parts.netloc}{parts.path}" != CSI_PERF or parts.fragment
                or set(query) != {"indexCode", "startDate", "endDate"}
                or any(len(value) != 1 for value in query.values()) or query["indexCode"] != [CODE]):
            raise RestoreError("请求必须唯一指向官方 CSI H00300 接口")
        start, end = _day(query["startDate"][0]), _day(query["endDate"][0])
        targets = [day for day in TARGET_DATES if start <= date.fromisoformat(day) <= end]
        if not 0 <= (end - start).days <= 45 or len(targets) != 1:
            raise RestoreError("短窗必须不超过 45 天且包含唯一指定年末日")
        target = targets[0]
        if target in rows:
            raise RestoreError(f"年末日 {target} 证据重复")
        fetched_at = entry["fetched_at"]
        try:
            if not isinstance(fetched_at, str) or not re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-5][0-9])", fetched_at):
                raise ValueError("须为带时区的 ISO 时间")
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            closed = datetime.combine(date.fromisoformat(target), time(15, 30), timezone(timedelta(hours=8)))
            if not closed <= fetched <= datetime.now(timezone.utc):
                raise ValueError("获取时间早于目标收盘或晚于当前时间")
        except ValueError as exc:
            raise RestoreError(f"fetched_at 非法：{exc}") from exc
        payload = _json(text)
        if (not isinstance(payload, dict) or str(payload.get("code")) != "200"
                or not isinstance(payload.get("data"), list)):
            raise RestoreError("短窗 CSI 响应不是成功的行情数组")
        seen, selected = set(), None
        for item in payload["data"]:
            if not isinstance(item, dict) or item.get("indexCode") != CODE:
                raise RestoreError("短窗响应每行必须明确标记 H00300")
            day = _day(item.get("tradeDate"))
            if not start <= day <= end or day in seen:
                raise RestoreError("短窗响应有窗口外日期或重复日期")
            seen.add(day)
            if day.isoformat() == target:
                selected = item
        if selected is None:
            raise RestoreError(f"短窗响应缺少 {target}")
        if any(selected.get(key) not in (None, "", "-", "--") for key in ("open", "high", "low")):
            raise RestoreError(f"{target} OHL 不是缺失值；不得覆盖或丢弃原始 OHL")
        parsed = parse_csindex_data([selected], preserve_null_close=True).rows[0]
        if (isinstance(selected.get("close"), bool) or parsed["close"] is None
                or not math.isfinite(parsed["close"]) or parsed["close"] <= 0):
            raise RestoreError(f"{target} 缺少正且有限的真实收盘")
        for field, raw_field in (("volume", "tradingVol"), ("amount", "tradingValue")):
            if (isinstance(selected.get(raw_field), bool) or
                    (selected.get(raw_field) not in (None, "", "-", "--")
                     and (parsed[field] is None or not math.isfinite(parsed[field])))):
                raise RestoreError(f"{target} {raw_field} 不是有限数值")
        rows[target] = dict(code=CODE, adj="raw", **parsed, source="csi", fetched_at=fetched_at)
    if set(rows) != set(TARGET_DATES):
        raise RestoreError("证据必须完整覆盖三个指定年末日")
    return entries, rows


def _audits(con):
    audits = []
    for run in con.execute("SELECT * FROM runs WHERE kind='backfill' ORDER BY run_id"):
        try:
            args = json.loads(run["args"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(args, dict) or args.get("offline_supplement") is not True:
            continue
        evidence = args.get("evidence")
        if (run["status"] != "ok" or args.get("format") != FORMAT
                or run["end_date"] != TARGET_DATES[-1] or not isinstance(evidence, dict)
                or not isinstance(evidence.get("manifest_text"), str)):
            raise RestoreError(f"补录 run {run['run_id']} 审计不完整")
        digest = hashlib.sha256(evidence["manifest_text"].encode("utf-8")).hexdigest()
        if args.get("manifest_sha256") != digest:
            raise RestoreError(f"补录 run {run['run_id']} 清单 sha256 不符")
        entries, rows = _validate(evidence["manifest_text"], evidence.get("response_texts"))
        requests = [dict(row) for row in con.execute("SELECT * FROM requests WHERE run_id=? ORDER BY seq", (run["run_id"],))]
        if requests != [dict(run_id=run["run_id"], seq=i, **entry) for i, entry in enumerate(entries)]:
            raise RestoreError(f"补录 run {run['run_id']} requests 与原始清单不符")
        inserted, preexisting = args.get("inserted_dates"), args.get("preexisting_exact_dates")
        if (not isinstance(inserted, list) or not isinstance(preexisting, list)
                or not all(isinstance(day, str) for day in inserted + preexisting)
                or sorted(inserted + preexisting) != list(TARGET_DATES)
                or con.execute("SELECT 1 FROM coverage WHERE run_id=? AND theme_id=?", (run["run_id"], THEME)).fetchone() is None):
            raise RestoreError(f"补录 run {run['run_id']} 写入记录不完整")
        audits.append((run["run_id"], digest, rows))
    return audits


def verified_supplement_rows(con, dates: set[str]) -> tuple[dict, list[int]]:
    """年度恢复只接纳有完整可重验补录审计的额外行，不由日期白名单直接放行。"""
    if not dates <= set(TARGET_DATES):
        raise RestoreError("年度证据外日期不在三日补录范围，拒绝覆盖")
    verified, run_ids = {}, []
    for run_id, _, rows in _audits(con):
        for day in dates:
            if day in verified and verified[day] != rows[day]:
                raise RestoreError(f"{day} 的补录审计存在冲突")
            verified[day] = rows[day]
        run_ids.append(run_id)
    if set(verified) != dates:
        raise RestoreError("年度证据外行情缺少可重验的补录审计")
    return verified, run_ids


def supplement(db: Path, manifest: Path, *, recorded_dir: Path | None = None, apply: bool = False) -> dict:
    DB.refuse_default_in_tests(db, DB.MARKET_DB)
    path = Path(db).resolve()
    if not path.is_file():
        raise RestoreError(f"行情库不存在：{path}")
    con = sqlite3.connect(path.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        version = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if version is None or version[0] != DB.SCHEMA_VERSION:
            raise RestoreError("行情库 schema 不符；补录不创建或迁移 schema")
        if apply:
            DB.require_date_constraints(con)
        manifest_text = Path(manifest).read_bytes().decode("utf-8")
        entries = _manifest(manifest_text)
        root = Path(recorded_dir if recorded_dir is not None else Path(manifest).parent).resolve(strict=True)
        responses = []
        for entry in entries:
            file = (root / entry["file"]).resolve(strict=True)
            if not file.is_relative_to(root) or not file.is_file():
                raise RestoreError("原响应不在录件目录内")
            responses.append(file.read_bytes().decode("utf-8"))
        entries, desired = _validate(manifest_text, responses)
        digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        base = con.execute("SELECT * FROM coverage_latest WHERE theme_id=?", (THEME,)).fetchone()
        if base is None or any(base[key] != value for key, value in
                               (("series_code", CODE), ("series_adj", "raw"), ("route_used", "csi"),
                                ("tr_code_used", CODE), ("price_only", "False"))):
            raise RestoreError("需已有 T01 H00300/raw/csi 全收益研究 coverage")
        if con.execute("SELECT 1 FROM coverage_latest WHERE exec_code=? LIMIT 1", (CODE,)).fetchone():
            raise RestoreError("H00300 被执行 coverage 引用，拒绝补录")
        existing = {row["date"]: dict(row) for row in con.execute("SELECT * FROM bars WHERE code=? AND adj='raw'", (CODE,))}
        if not existing or any(row["source"] != "csi" for row in existing.values()):
            raise RestoreError("需已有同源 H00300 行情；不得改变序列来源")
        for day, row in desired.items():
            if day in existing and existing[day] != row:
                raise RestoreError(f"已有 {day} 与补录证据冲突（含 NULL / 来源 / 获取时刻），拒绝覆盖")
        audits = _audits(con)
        for _, _, rows in audits:
            if rows != desired:
                raise RestoreError("已有补录审计与本次证据冲突")
        previous = next((run_id for run_id, sha, _ in reversed(audits) if sha == digest), None)
        added = [desired[day] for day in TARGET_DATES if day not in existing]
        combined = sorted((existing | desired).values(), key=lambda row: row["date"])
        cov = _coverage(base, combined, base["series_name"])
        needs_write = bool(added or previous is None or any(cov[key] != base[key] for key in DB.COVERAGE_COLUMNS))
        report = {"operation": "offline_supplement", "dry_run": not apply, "applied": False,
                  "changed": False, "would_change": needs_write, "idempotent": not needs_write,
                  "manifest_sha256": digest, "run_id": previous, "verified_requests": len(entries),
                  "target_dates": list(TARGET_DATES), "rows_to_insert": len(added), "rows": len(combined),
                  "inserted_dates": [row["date"] for row in added],
                  "preexisting_exact_dates": [day for day in TARGET_DATES if day in existing]}
        if not apply or not needs_write:
            con.rollback()
            return report
        at = DB.now()
        marker = f"offline_supplement H00300 manifest_sha256={digest}"
        cov["notes"] = base["notes"] if marker in base["notes"] else " | ".join(filter(None, (base["notes"], marker)))
        cov["checked_at"] = at
        args = {"offline_supplement": True, "format": FORMAT, "manifest_sha256": digest,
                "inserted_dates": report["inserted_dates"], "preexisting_exact_dates": report["preexisting_exact_dates"],
                "evidence": {"manifest_text": manifest_text, "response_texts": responses}}
        source_run = con.execute("SELECT universe_sha256 FROM runs WHERE run_id=?", (base["run_id"],)).fetchone()
        cur = con.execute("INSERT INTO runs(kind,started_at,finished_at,end_date,args,git_commit,universe_sha256,status) "
                          "VALUES ('backfill',?,?,?,?,?,?,'ok')", (at, at, TARGET_DATES[-1], json.dumps(args, ensure_ascii=False),
                          DB.git_head(), source_run[0] if source_run else None))
        run_id = cur.lastrowid
        con.executemany("INSERT INTO requests(run_id,seq,url,fetched_at,bytes,sha256,error,file) VALUES (?,?,?,?,?,?,?,?)",
                        [(run_id, i, *(entry[key] for key in REQUEST_COLUMNS)) for i, entry in enumerate(entries)])
        con.executemany(f"INSERT INTO bars ({', '.join(BAR_COLUMNS)}) VALUES ({', '.join('?' for _ in BAR_COLUMNS)})",
                        [tuple(row[key] for key in BAR_COLUMNS) for row in added])
        con.execute(f"INSERT INTO coverage(run_id, {', '.join(DB.COVERAGE_COLUMNS)}) VALUES (?, {', '.join('?' for _ in DB.COVERAGE_COLUMNS)})",
                    (run_id, *(cov[key] for key in DB.COVERAGE_COLUMNS)))
        con.commit()
        report.update(applied=True, changed=True, run_id=run_id)
        return report
    except (OSError, UnicodeError, sqlite3.DatabaseError) as exc:
        con.rollback()
        raise RestoreError(f"离线补录失败，未写入：{exc}") from exc
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
