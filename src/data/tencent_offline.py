"""357d2f3 腾讯价格指数候选的固定批次离线导入；无抓取与路由回退。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.indicators.calendar import load_trading_days
from . import db as DB

INDEX_PATH = DB.ROOT / "operations/work_logs/2026-10-06-tencent-price-candidates-index.json"
INDEX_SHA256 = "f2865c4884cc9d5c290c03f17afc75c2a74550376d31a2f9cbb1174c30a8603b"
FORMAT = "tencent-price-only-annual-candidates-v1"
SOURCE = "tencent_price_index_offline"
ENDPOINT = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
NAMES = {"000852": "中证1000", "000905": "中证500"}
END = "2026-09-30"
REQUEST_COLUMNS = ("url", "fetched_at", "bytes", "sha256", "error", "file")
BAR_COLUMNS = ("code", "adj", "date", "open", "high", "low", "close", "volume", "amount", "source", "fetched_at")


class PriceImportError(ValueError):
    """证据、日历、目标序列或审计冲突；事务整体拒绝。"""


def _json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PriceImportError(f"证据 JSON 重复字段：{key}")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise PriceImportError(f"证据 JSON 非法：{exc}") from exc


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise PriceImportError(f"日期须为 YYYY-MM-DD：{value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PriceImportError(f"非法日期：{value}") from exc


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-5][0-9])", value):
        raise PriceImportError("获取时刻须为带时区的 ISO 时间")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PriceImportError("获取时刻非法") from exc


def _price(value):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError()
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError()
        return result
    except (ValueError, OverflowError) as exc:
        raise PriceImportError(f"OHLC 须为正且有限的真实数值：{value!r}") from exc


def _verify(index, responses, calendar):
    windows = index.get("windows") if isinstance(index, dict) else None
    if (not isinstance(windows, list) or len(windows) != 44 or len(responses) != 44
            or index.get("format") != FORMAT or index.get("request_param_qfq_is_not_total_return") is not True
            or index.get("volume_unit") != "unverified"):
        raise PriceImportError("证据索引须完整包含两个价格指数的 44 个年度窗口")
    expected = {(code, year) for code in NAMES for year in range(2005, 2027)}
    seen, overlaps, desired, requests = set(), {}, {}, []
    calset = set(calendar)
    for window, text in zip(windows, responses):
        if not isinstance(window, dict):
            raise PriceImportError("年度窗口不是对象")
        code, year = window.get("code"), window.get("year")
        if not isinstance(code, str) or type(year) is not int or (code, year) not in expected or (code, year) in seen:
            raise PriceImportError("代码或年度窗口不在本批次范围，或窗口重复")
        seen.add((code, year))
        start, end = f"{year}-01-01", min(f"{year}-12-31", END)
        symbol, identity = f"sh{code}", ["1", NAMES[code], code]
        param = f"{symbol},day,{start},{end},320,qfq"
        if (window.get("symbol") != symbol or window.get("start") != start or window.get("end") != end
                or window.get("price_only") is not True or window.get("volume_unit") != "unverified"
                or window.get("request_param") != param or window.get("identity") != identity
                or window.get("http_status") != 200 or window.get("outcome") != "verified"):
            raise PriceImportError(f"{code}/{year} 索引身份、价格口径或年度窗口不符")
        entry = window.get("request")
        if not isinstance(entry, dict) or set(entry) != set(REQUEST_COLUMNS):
            raise PriceImportError("请求元数据字段不完整")
        raw = text.encode("utf-8")
        if (entry["error"] not in (None, "") or type(entry["bytes"]) is not int or entry["bytes"] != len(raw)
                or not isinstance(entry["sha256"], str) or hashlib.sha256(raw).hexdigest() != entry["sha256"]):
            raise PriceImportError(f"{code}/{year} 原响应 bytes / sha256 不符或有请求错误")
        if not isinstance(entry["url"], str):
            raise PriceImportError("请求 URL 非法")
        parts = urlsplit(entry["url"])
        if (f"{parts.scheme}://{parts.netloc}{parts.path}" != ENDPOINT or parts.fragment
                or parse_qs(parts.query, keep_blank_values=True) != {"param": [param]}):
            raise PriceImportError("请求不唯一指向已批准的腾讯价格指数年度接口")
        fetched = _time(entry["fetched_at"])
        closed = datetime.combine(_day(end), time(15, 30), timezone(timedelta(hours=8)))
        if not closed <= fetched <= datetime.now(timezone.utc):
            raise PriceImportError("获取时间早于窗口收盘或晚于当前时间")
        payload = _json(text)
        if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
            raise PriceImportError("腾讯响应业务 code 不是 0")
        data = payload.get("data")
        item = data.get(symbol) if isinstance(data, dict) else None
        qt = item.get("qt") if isinstance(item, dict) else None
        quote = qt.get(symbol) if isinstance(qt, dict) else None
        if not isinstance(quote, list) or quote[:3] != identity:
            raise PriceImportError(f"响应身份不符：须为 {symbol}/{NAMES[code]}")
        raw_rows = item.get("day")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise PriceImportError("缺少原始 day 行情；不得回退 qfqday")
        dates, selected = [], []
        for row in raw_rows:
            if not isinstance(row, list) or len(row) < 6:
                raise PriceImportError("day 行须含 date,open,close,high,low,原始量")
            day = _day(row[0]).isoformat()
            if dates and day <= dates[-1]:
                raise PriceImportError("原响应日期重复或未严格递增，不以去重掩盖")
            dates.append(day)
            opening, close, high, low = map(_price, row[1:5])
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise PriceImportError(f"{code}/{day} OHLC 高低顺序非法")
            if day not in calset:
                raise PriceImportError(f"{code}/{day} 不在官方 calendar 中（含窗外原始行）")
            prices = (opening, close, high, low)
            key = (code, day)
            if key in overlaps and overlaps[key] != prices:
                raise PriceImportError(f"{code}/{day} 跨年度原响应 OHLC 不一致")
            overlaps[key] = prices
            if start <= day <= end:
                selected.append(day)
                desired[key] = dict(code=code, adj="raw", date=day, open=opening, high=high, low=low, close=close,
                                    volume=None, amount=None, source=SOURCE, fetched_at=entry["fetched_at"])
        days = [day for day in calendar if start <= day <= end]
        latest_close = datetime.combine(_day(dates[-1]), time(15, 30), timezone(timedelta(hours=8)))
        if fetched < latest_close:
            raise PriceImportError("原响应含获取时刻尚未收盘的行情（含窗外行）")
        if not days or selected != days:
            raise PriceImportError(f"{code}/{year} 与官方日历不符：缺日 {sorted(set(days)-set(selected))[:5]}；额外 {sorted(set(selected)-set(days))[:5]}")
        checks = {"raw_rows": len(dates), "raw_first": dates[0], "raw_last": dates[-1],
                  "window_rows": len(selected), "first": selected[0], "last": selected[-1],
                  "discarded_outside_window": len(dates) - len(selected), "expected_calendar_rows": len(days),
                  "missing_calendar_dates": [], "extra_dates": [], "duplicate_dates": {},
                  "invalid_ohlc_rows": [], "raw_duplicate_dates": {}}
        if any(window.get(key) != value for key, value in checks.items()):
            raise PriceImportError(f"{code}/{year} 重新计算的年度检查与索引不符")
        requests.append(entry)
    if seen != expected:
        raise PriceImportError("缺年度窗口")
    return requests, desired


def _existing_audit(con, manifest_text, responses, requests, series, calendar_sha256, desired):
    previous = None
    fingerprints = {(r["url"], r["sha256"]) for r in requests}
    for run in con.execute("SELECT * FROM runs ORDER BY run_id"):
        recorded = [dict(r) for r in con.execute("SELECT * FROM requests WHERE run_id=? ORDER BY seq", (run["run_id"],))]
        related = any((r["url"], r["sha256"]) in fingerprints for r in recorded)
        try:
            args = json.loads(run["args"] or "{}")
        except (TypeError, ValueError):
            if related or "offline_tencent_price_import" in (run["args"] or ""):
                raise PriceImportError(f"腾讯证据关联 run {run['run_id']} 的 args 已损坏") from None
            continue
        marked = isinstance(args, dict) and ("offline_tencent_price_import" in args or args.get("source") == SOURCE)
        if not related and not marked:
            continue
        if (not isinstance(args, dict) or args.get("offline_tencent_price_import") is not True
                or run["kind"] != "backfill" or run["status"] != "ok" or not run["finished_at"] or run["end_date"] != END
                or args.get("format") != FORMAT or args.get("manifest_sha256") != INDEX_SHA256
                or args.get("price_only") is not True or args.get("source") != SOURCE or args.get("series") != series
                or args.get("evidence_commit") != "357d2f3068ad2bcc7820917a9a41318471d5e64b"
                or args.get("calendar_sha256") != calendar_sha256
                or args.get("evidence") != {"manifest_text": manifest_text, "response_texts": responses}):
            raise PriceImportError(f"既有腾讯导入 run {run['run_id']} 审计不符，拒绝重写")
        if recorded != [dict(run_id=run["run_id"], seq=i, **entry) for i, entry in enumerate(requests)]:
            raise PriceImportError("既有腾讯导入 requests 与原始证据不符")
        inserted, preexisting = args.get("inserted_dates"), args.get("preexisting_exact_dates")
        for code in NAMES:
            a, b = inserted.get(code) if isinstance(inserted, dict) else None, preexisting.get(code) if isinstance(preexisting, dict) else None
            if (not isinstance(a, list) or not isinstance(b, list) or not all(isinstance(d, str) for d in a+b)
                    or sorted(a+b) != sorted(day for c, day in desired if c == code)):
                raise PriceImportError("既有腾讯导入缺少完整插入/保留记录")
        previous = run["run_id"]
    return previous


def import_prices(db: Path, recorded_dir: Path, *, apply: bool = False) -> dict:
    """固定批准索引；dry-run 真只读，apply 单一事务，原文与请求随作业完整保存。"""
    DB.refuse_default_in_tests(db, DB.MARKET_DB)
    path = Path(db).resolve()
    if not path.is_file():
        raise PriceImportError("行情库不存在；离线导入不建库")
    con = sqlite3.connect(path.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        if not apply:
            con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        version = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if version is None or version[0] != DB.SCHEMA_VERSION:
            raise PriceImportError("行情库 schema 不符，不创建或迁移")
        if apply:
            DB.require_date_constraints(con)
        manifest_raw = INDEX_PATH.read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest() != INDEX_SHA256:
            raise PriceImportError("证据索引 SHA256 与批准的 357d2f3 批次不符")
        manifest_text = manifest_raw.decode("utf-8")
        index = _json(manifest_text)
        if not isinstance(index, dict) or not isinstance(index.get("windows"), list):
            raise PriceImportError("证据索引缺少 windows")
        root = Path(recorded_dir).resolve(strict=True)
        if not root.is_dir():
            raise PriceImportError("原响应目录不存在")
        responses = []
        for window in index["windows"]:
            entry = window.get("request", {}) if isinstance(window, dict) else {}
            filename = entry.get("file") if isinstance(entry, dict) else None
            if not isinstance(filename, str) or not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
                raise PriceImportError("原响应须为录件目录内的安全相对路径")
            file = (root / filename).resolve(strict=True)
            if not file.is_relative_to(root) or not file.is_file():
                raise PriceImportError("原响应不在录件目录内")
            responses.append(file.read_bytes().decode("utf-8"))
        days = load_trading_days(con)
        if days is None:
            raise PriceImportError("缺少官方 calendar，不以工作日推造")
        calendar = [d.date().isoformat() for d in days]
        requests, desired = _verify(index, responses, calendar)
        relevant_days = [d for d in calendar if "2005-01-01" <= d <= END]
        calendar_sha = hashlib.sha256(json.dumps(relevant_days, separators=(",", ":")).encode()).hexdigest()
        series = [{"code": code, "name": name, "adj": "raw", "source": SOURCE, "price_only": True,
                   "volume_unit": "unverified", "rows": sum(c == code for c, _ in desired),
                   "first_date": relevant_days[0], "last_date": relevant_days[-1]} for code, name in NAMES.items()]
        existing = {(r["code"], r["date"]): dict(r) for r in con.execute(
            "SELECT * FROM bars WHERE code IN ('000852','000905') AND adj='raw'")}
        for key, row in existing.items():
            if desired.get(key) != row:
                raise PriceImportError(f"已有 {key} 与证据冲突或在证据范围外（含来源/获取时刻），拒绝覆盖")
        added = [row for key, row in sorted(desired.items()) if key not in existing]
        previous = _existing_audit(con, manifest_text, responses, requests, series, calendar_sha, desired)
        if previous is not None and added:
            raise PriceImportError("已有成功导入审计但行情缺失，停止报告，不静默修写")
        changes = bool(added or previous is None)
        report = {"operation": "offline_tencent_price_import", "dry_run": not apply, "applied": False,
                  "changed": False, "would_change": changes, "idempotent": not changes, "run_id": previous,
                  "manifest_sha256": INDEX_SHA256, "source": SOURCE, "price_only": True,
                  "series": series, "verified_requests": len(requests), "rows": len(desired), "rows_to_insert": len(added),
                  "raw_rows": sum(w["raw_rows"] for w in index["windows"]),
                  "discarded_outside_window": sum(w["discarded_outside_window"] for w in index["windows"])}
        if not apply or not changes:
            con.rollback()
            return report
        args = {"offline_tencent_price_import": True, "format": FORMAT, "manifest_sha256": INDEX_SHA256,
                "source": SOURCE, "price_only": True, "series": series, "calendar_sha256": calendar_sha,
                "evidence_commit": "357d2f3068ad2bcc7820917a9a41318471d5e64b",
                "inserted_dates": {code: [r["date"] for r in added if r["code"] == code] for code in NAMES},
                "preexisting_exact_dates": {code: sorted(day for c, day in existing if c == code) for code in NAMES},
                "evidence": {"manifest_text": manifest_text, "response_texts": responses}}
        at = DB.now()
        cur = con.execute("INSERT INTO runs(kind,started_at,finished_at,end_date,args,git_commit,status) VALUES('backfill',?,?,?,?,?,'ok')",
                          (at, at, END, json.dumps(args, ensure_ascii=False), DB.git_head()))
        run_id = cur.lastrowid
        con.executemany("INSERT INTO requests(run_id,seq,url,fetched_at,bytes,sha256,error,file) VALUES(?,?,?,?,?,?,?,?)",
                        [(run_id, i, *(r[k] for k in REQUEST_COLUMNS)) for i, r in enumerate(requests)])
        con.executemany(f"INSERT INTO bars({','.join(BAR_COLUMNS)}) VALUES({','.join('?' for _ in BAR_COLUMNS)})",
                        [tuple(row[k] for k in BAR_COLUMNS) for row in added])
        con.commit()
        report.update(applied=True, changed=True, run_id=run_id)
        return report
    except (OSError, UnicodeError, sqlite3.DatabaseError, ValueError) as exc:
        con.rollback()
        raise PriceImportError(f"离线价格指数导入失败，未写入：{exc}") from exc
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
