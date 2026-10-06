"""腾讯价格指数导入的完整合成年度证据；不访问正式行情库或网络。"""
import contextlib
import copy
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import tests  # noqa: F401 — 默认正式库测试防线
from src.data import db as DB
from src.data import tencent_offline as importer
from src.data.date_constraints import DATE_CONSTRAINT_KEY, upgrade
from tests.data.test_date_constraints import create_legacy


END = date(2026, 9, 30)
CODES = {"000852": "中证1000", "000905": "中证500"}
SOURCE = "tencent_price_index_offline"
ENDPOINT = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
TABLES = {"meta": "key", "runs": "run_id", "bars": "code,adj,date",
          "coverage": "run_id,theme_id", "requests": "run_id,seq",
          "update_results": "run_id,seq", "calendar": "date", "universe": "theme_id",
          "sqlite_sequence": "name"}


class TencentOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "market.sqlite"
        self.recorded = self.root / "recorded"
        self.recorded.mkdir()
        self.manifest = self.root / "index.json"
        self.con = DB.connect(self.db)
        self.addCleanup(self.con.close)
        self.calendar = []
        day = date(2005, 1, 3)
        while day <= END:
            if day.weekday() < 5:
                self.calendar.append(day.isoformat())
            day += timedelta(days=1)
        with self.con:
            self.con.executemany("INSERT INTO calendar VALUES (?)", [(d,) for d in self.calendar])
            self.old_run = DB.start_run(self.con, "backfill", end=END, args={"historical": "must survive"},
                                        universe_sha256="original-universe")
            DB.write_requests(self.con, self.old_run, [{"url": "https://example.org/original", "file": "old.body",
                "fetched_at": "old-time", "bytes": 7, "sha256": "old-sha", "error": None}])
            coverage = {key: "" for key in DB.COVERAGE_COLUMNS}
            coverage.update(theme_id="T02", code="000905", series_code="H00905", series_adj="raw",
                            price_only="False", rows="1", exec_code="510500", notes="unchanged selection")
            DB.write_coverage(self.con, self.old_run, [coverage])
            self.con.execute("INSERT INTO universe VALUES (0,'T02',?)", (json.dumps(coverage),))
            self.con.execute("INSERT INTO update_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                self.old_run, 0, "T02", "execution", "510500", "hfq", "eastmoney_etf_hfq", 1,
                "2026-09-29", 1, 0, "2026-09-30", None))
            self.con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                ("H00852", "raw", "2026-09-30", None, None, None, 500, 7, 8, "csi", "original-total-return"),
                ("H00905", "raw", "2026-09-30", None, None, None, 600, 8, 9, "csi", "original-total-return"),
                ("H00300", "raw", "2005-01-08", None, None, None, 123, None, None, "csi", "original-nontrading"),
                ("510500", "hfq", "2026-09-30", 1, 3, 1, 2, 7, 8, "eastmoney_etf_hfq", "original-execution")])
            DB.finish_run(self.con, self.old_run)
        self.document = {
            "format": "tencent-price-only-annual-candidates-v1", "base_commit": "1" * 40,
            "evidence_dir": "synthetic-test-only", "finished_at": "2026-10-01T00:59:59+00:00",
            "source_db_sha256": "2" * 64, "database_unchanged": True,
            "request_param_qfq_is_not_total_return": True, "volume_unit": "unverified", "windows": [],
        }
        self.payloads = []
        for code, name in CODES.items():
            for year in range(2005, 2027):
                start, end = f"{year}-01-01", min(date(year, 12, 31), END).isoformat()
                days = [d for d in self.calendar if start <= d <= end]
                overlap = [d for d in self.calendar if d < start][-2:]
                symbol = "sh" + code
                param = f"{symbol},day,{start},{end},320,qfq"
                payload = {"code": 0, "msg": "", "data": {symbol: {
                    "day": [self.price_row(d, code) for d in overlap + days],
                    "qt": {symbol: ["1", name, code, "unused quote fields"]},
                }}}
                entry = {
                    "code": code, "symbol": symbol, "year": year, "start": start, "end": end,
                    "price_only": True, "volume_unit": "unverified", "request_param": param,
                    "request": {"url": ENDPOINT + "?" + urlencode({"param": param}),
                        "fetched_at": f"2026-10-01T00:{len(self.payloads):02d}:00+00:00",
                        "error": None, "file": f"response-{code}-{year}.body"},
                    "http_status": 200, "identity": ["1", name, code], "outcome": "verified",
                    "raw_rows": len(days) + len(overlap), "raw_first": (overlap + days)[0],
                    "raw_last": days[-1], "window_rows": len(days), "first": days[0], "last": days[-1],
                    "discarded_outside_window": len(overlap), "expected_calendar_rows": len(days),
                    "missing_calendar_dates": [], "extra_dates": [], "duplicate_dates": {},
                    "invalid_ohlc_rows": [], "raw_duplicate_dates": {},
                }
                self.document["windows"].append(entry)
                self.payloads.append(payload)
                self.write_payload(len(self.payloads) - 1)
        self.write_manifest()
        for target in ("src.data.http.get", "src.data.http.urlopen", "src.data.sources.fetch_tencent"):
            # 某些构建没有 fetch_tencent，网络底层仍始终封死。
            patcher = mock.patch(target, side_effect=AssertionError("offline import attempted network"), create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def price_row(day, code):
        value = 100 + (date.fromisoformat(day).toordinal() % 1000) + (1000 if code == "000905" else 0)
        return [day, str(value), str(value + 1), str(value + 2), str(value - 2), "99999999"]

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.document, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_payload(self, index):
        entry = self.document["windows"][index]["request"]
        raw = json.dumps(self.payloads[index], ensure_ascii=False).encode("utf-8")
        (self.recorded / entry["file"]).write_bytes(raw)
        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write_manifest()

    def patch_index(self):
        return mock.patch.multiple(importer, INDEX_PATH=self.manifest,
                                   INDEX_SHA256=hashlib.sha256(self.manifest.read_bytes()).hexdigest())

    def call(self, **kwargs):
        with self.patch_index():
            return importer.import_prices(self.db, self.recorded, **kwargs)

    def snapshot(self):
        return DB.content_sha256(self.con, TABLES)

    def reject_unchanged(self):
        snapshot, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaises(importer.PriceImportError):
            self.call(apply=True)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def target_row(self, index=0, *, source=SOURCE, day=None, close=None):
        window = self.document["windows"][index]
        day = day or window["first"]
        raw = self.price_row(day, window["code"])
        return (window["code"], "raw", day, float(raw[1]), float(raw[3]), float(raw[4]),
                float(raw[2]) if close is None else close, None, None, source, window["request"]["fetched_at"])

    def test_default_dry_run_is_byte_for_byte_readonly(self):
        snapshot, disk = self.snapshot(), DB.sha256_file(self.db)
        report = self.call()
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["rows_to_insert"], 2 * len(self.calendar))
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(DB.sha256_file(self.db), disk)
        self.assertFalse(list(self.root.glob("*.sqlite-*")))

    def test_apply_imports_raw_price_only_and_preserves_every_other_history(self):
        before = {table: [tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {order}")]
                  for table, order in TABLES.items() if table != "sqlite_sequence"}
        result = self.call(apply=True)
        self.assertTrue(result["applied"])
        self.assertEqual(result["rows_to_insert"], 2 * len(self.calendar))
        for code in CODES:
            rows = self.con.execute("SELECT * FROM bars WHERE code=? ORDER BY date", (code,)).fetchall()
            self.assertEqual([r["date"] for r in rows], self.calendar)
            for row in rows:
                raw = self.price_row(row["date"], code)
                self.assertEqual((row["open"], row["close"], row["high"], row["low"]),
                                 tuple(float(value) for value in raw[1:5]))
                self.assertEqual((row["source"], row["adj"], row["volume"], row["amount"]),
                                 (SOURCE, "raw", None, None))
                window = next(w for w in self.document["windows"] if w["code"] == code and w["year"] == int(row["date"][:4]))
                self.assertEqual(row["fetched_at"], window["request"]["fetched_at"])
        self.assertIsNotNone(self.con.execute("SELECT 1 FROM bars WHERE code='000852' AND date='2008-02-29'").fetchone())
        for table in ("meta", "calendar", "coverage", "universe", "update_results"):
            self.assertEqual([tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {TABLES[table]}")], before[table])
        for table in ("runs", "requests"):
            self.assertEqual([tuple(r) for r in self.con.execute(
                f"SELECT * FROM {table} WHERE run_id <= ? ORDER BY {TABLES[table]}", (self.old_run,))], before[table])
        other = self.con.execute("SELECT * FROM bars WHERE code NOT IN ('000852','000905') ORDER BY code,adj,date")
        self.assertEqual([tuple(r) for r in other], before["bars"])
        self.assertEqual(self.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_complete_audit_contains_exact_manifest_responses_and_requests(self):
        result = self.call(apply=True)
        run = self.con.execute("SELECT * FROM runs WHERE run_id=?", (result["run_id"],)).fetchone()
        self.assertEqual((run["kind"], run["status"], run["end_date"]), ("backfill", "ok", END.isoformat()))
        args = json.loads(run["args"])
        self.assertIs(args["offline_tencent_price_import"], True)
        self.assertIs(args["price_only"], True)
        self.assertEqual(args["manifest_sha256"], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(args["evidence"]["manifest_text"], self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(args["evidence"]["response_texts"], [
            (self.recorded / w["request"]["file"]).read_text(encoding="utf-8") for w in self.document["windows"]])
        self.assertEqual({s["code"] for s in args["series"]}, set(CODES))
        for series in args["series"]:
            self.assertEqual((series["adj"], series["source"], series["price_only"]), ("raw", SOURCE, True))
        requests = self.con.execute("SELECT * FROM requests WHERE run_id=? ORDER BY seq", (result["run_id"],)).fetchall()
        self.assertEqual(len(requests), 44)
        for seq, (record, window) in enumerate(zip(requests, self.document["windows"])):
            self.assertEqual(record["seq"], seq)
            for key, value in window["request"].items():
                self.assertEqual(record[key], value)

    def test_repeated_apply_is_byte_idempotent_and_preserves_audit_id(self):
        first = self.call(apply=True)
        snapshot, disk = self.snapshot(), DB.sha256_file(self.db)
        again = self.call(apply=True)
        self.assertTrue(again["idempotent"])
        self.assertFalse(again["changed"])
        self.assertEqual(again["run_id"], first["run_id"])
        self.assertEqual(again["rows_to_insert"], 0)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_existing_exact_row_is_preserved_and_missing_rows_receive_audit(self):
        existing = self.target_row()
        with self.con:
            self.con.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", existing)
        result = self.call(apply=True)
        self.assertEqual(result["rows_to_insert"], 2 * len(self.calendar) - 1)
        actual = self.con.execute("SELECT * FROM bars WHERE code=? AND date=?", (existing[0], existing[2])).fetchone()
        self.assertEqual(tuple(actual), existing)
        self.assertIsNotNone(result["run_id"])
        self.assertTrue(self.call(apply=True)["idempotent"])

    def test_existing_conflict_other_source_extra_day_and_changed_timestamp_reject(self):
        variants = [self.target_row(close=999999), self.target_row(source="csi"),
                    self.target_row(day="2004-12-31"), self.target_row(day="2005-01-08"),
                    (*self.target_row()[:-1], "2026-10-01T00:00:01+00:00")]
        for row in variants:
            with self.subTest(row=row):
                with self.con:
                    self.con.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
                self.reject_unchanged()
                with self.con:
                    self.con.execute("DELETE FROM bars WHERE code IN ('000852','000905')")

    def test_audited_missing_row_or_tampered_run_or_request_rejects(self):
        result = self.call(apply=True)
        saved = tuple(self.con.execute("SELECT * FROM bars WHERE code='000852' ORDER BY date LIMIT 1").fetchone())
        with self.con:
            self.con.execute("DELETE FROM bars WHERE code=? AND date=?", (saved[0], saved[2]))
        self.reject_unchanged()
        with self.con:
            self.con.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", saved)
        original = self.con.execute("SELECT args FROM runs WHERE run_id=?", (result["run_id"],)).fetchone()[0]
        variants = ["{broken JSON", "{}"]
        changes = [lambda args: args.pop("offline_tencent_price_import"),
                   lambda args: args.update(offline_tencent_price_import=False),
                   lambda args: args.update(source="csi"),
                   lambda args: args["series"][0].update(price_only=False),
                   lambda args: args["evidence"]["response_texts"].__setitem__(
                       0, args["evidence"]["response_texts"][0] + " ")]
        for change in changes:
            args = json.loads(original)
            change(args)
            variants.append(json.dumps(args))
        for number, changed in enumerate(variants):
            with self.subTest(args_variant=number):
                with self.con:
                    self.con.execute("UPDATE runs SET args=? WHERE run_id=?", (changed, result["run_id"]))
                self.reject_unchanged()
                with self.con:
                    self.con.execute("UPDATE runs SET args=? WHERE run_id=?", (original, result["run_id"]))
        with self.con:
            self.con.execute("UPDATE runs SET kind='probe' WHERE run_id=?", (result["run_id"],))
        self.reject_unchanged()
        with self.con:
            self.con.execute("UPDATE runs SET kind='backfill' WHERE run_id=?", (result["run_id"],))
        request = tuple(self.con.execute("SELECT * FROM requests WHERE run_id=? AND seq=0", (result["run_id"],)).fetchone())
        with self.con:
            self.con.execute("DELETE FROM requests WHERE run_id=? AND seq=0", (result["run_id"],))
        self.reject_unchanged()
        with self.con:
            self.con.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?)", request)
            self.con.execute("UPDATE requests SET sha256=? WHERE run_id=? AND seq=0", ("0" * 64, result["run_id"]))
        self.reject_unchanged()
        with self.con:
            self.con.execute("DELETE FROM requests WHERE run_id=? AND seq=0", (result["run_id"],))
            self.con.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?)", request)
            # 不相关的历史 args 可以保留原状，不能把本包变成历史审计清洗。
            self.con.execute("UPDATE runs SET args='{unrelated historical JSON' WHERE run_id=?", (self.old_run,))
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        self.assertTrue(self.call(apply=True)["idempotent"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_insert_failure_rolls_back_both_series_and_all_new_audit(self):
        with self.con:
            self.con.execute("CREATE TRIGGER fail_second_series BEFORE INSERT ON bars WHEN NEW.code='000905' "
                             "BEGIN SELECT RAISE(ABORT, 'synthetic second-series failure'); END")
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaises((importer.PriceImportError, sqlite3.DatabaseError)):
            self.call(apply=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_manifest_pin_and_original_response_hash_are_rechecked(self):
        before = DB.sha256_file(self.db)
        with mock.patch.multiple(importer, INDEX_PATH=self.manifest, INDEX_SHA256="0" * 64):
            with self.assertRaises(importer.PriceImportError):
                importer.import_prices(self.db, self.recorded, apply=True)
        self.assertEqual(DB.sha256_file(self.db), before)
        path = self.recorded / self.document["windows"][0]["request"]["file"]
        path.write_bytes(path.read_bytes() + b" ")
        self.reject_unchanged()

    def test_manifest_scope_requires_exact_44_windows_and_price_only(self):
        original = copy.deepcopy(self.document)
        variants = [lambda d: d.update(format="different"),
                    lambda d: d["windows"].pop(),
                    lambda d: d["windows"].append(copy.deepcopy(d["windows"][0])),
                    lambda d: d["windows"].__setitem__(1, copy.deepcopy(d["windows"][0])),
                    lambda d: d["windows"][0].update(code="000300"),
                    lambda d: d["windows"][0].update(start="2004-01-01"),
                    lambda d: d["windows"][-1].update(end="2026-12-31"),
                    lambda d: d["windows"][0].update(price_only=False),
                    lambda d: d["windows"][0].update(volume_unit="shares"),
                    lambda d: d.update(request_param_qfq_is_not_total_return=False)]
        for number, change in enumerate(variants):
            with self.subTest(variant=number):
                self.document = copy.deepcopy(original)
                change(self.document)
                self.write_manifest()
                self.reject_unchanged()

    def test_source_url_and_declared_request_window_are_strict(self):
        original = copy.deepcopy(self.document)
        url = original["windows"][0]["request"]["url"]
        variants = [url.replace("https://", "http://"), url.replace("proxy.finance.qq.com", "example.org"),
                    url.replace("newfqkline", "fqkline"), url + "#fragment", url + "&param=duplicate",
                    url + "&other=1", url.replace("000852", "000905"), url.replace("2005-01-01", "2004-01-01"),
                    url.replace("qfq", "hfq"), "https://["]
        for value in variants:
            with self.subTest(url=value):
                self.document = copy.deepcopy(original)
                self.document["windows"][0]["request"]["url"] = value
                self.write_manifest()
                self.reject_unchanged()

    def test_request_metadata_timestamp_path_and_missing_file_fail_closed(self):
        original = copy.deepcopy(self.document)
        outside = self.root / "outside.body"
        outside.write_bytes((self.recorded / original["windows"][0]["request"]["file"]).read_bytes())
        variants = [("bytes", True), ("bytes", 1), ("sha256", "0" * 64), ("error", "HTTP 403"),
                    ("fetched_at", "2026-10-01T00:00:00"), ("fetched_at", "not-a-time"),
                    ("fetched_at", "2005-01-01T00:00:00+00:00"), ("fetched_at", "2099-01-01T00:00:00+00:00"),
                    ("file", "../outside.body"), ("file", str(outside)), ("file", "missing.body")]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                self.document = copy.deepcopy(original)
                self.document["windows"][0]["request"][key] = value
                self.write_manifest()
                self.reject_unchanged()
        self.document = copy.deepcopy(original)
        link = self.recorded / "linked.body"
        link.symlink_to(outside)
        self.document["windows"][0]["request"]["file"] = link.name
        self.write_manifest()
        self.reject_unchanged()

    def test_fetch_time_is_after_current_window_close_not_just_after_its_start(self):
        entry = self.document["windows"][-1]["request"]
        # 14:59 北京时间仍是当日盘中；UTC 时间戳不能仅与窗口开始或午夜比较。
        entry["fetched_at"] = "2026-09-30T06:59:59+00:00"
        self.write_manifest()
        self.reject_unchanged()
        entry["fetched_at"] = "2026-09-30T08:00:00+00:00"
        self.write_manifest()
        self.assertEqual(self.call()["rows_to_insert"], 2 * len(self.calendar))

    def test_missing_database_is_not_created_by_dry_run_or_apply(self):
        missing = self.root / "nonexistent.sqlite"
        for apply in (False, True):
            with self.subTest(apply=apply), self.patch_index():
                with self.assertRaises(importer.PriceImportError):
                    importer.import_prices(missing, self.recorded, apply=apply)
                self.assertFalse(missing.exists())

    def test_business_response_and_live_identity_are_checked(self):
        original = copy.deepcopy(self.payloads[0])
        variants = [lambda p: p.update(code=1), lambda p: p.update(code=True),
                    lambda p: p["data"]["sh000852"]["qt"]["sh000852"].__setitem__(0, "2"),
                    lambda p: p["data"]["sh000852"]["qt"]["sh000852"].__setitem__(1, "沪深300"),
                    lambda p: p["data"]["sh000852"]["qt"]["sh000852"].__setitem__(2, "H00852"),
                    lambda p: p["data"].__setitem__("sh000852", {"day": []}),
                    lambda p: p["data"]["sh000852"].update(qfqday=p["data"]["sh000852"].pop("day"))]
        for number, change in enumerate(variants):
            with self.subTest(variant=number):
                self.payloads[0] = copy.deepcopy(original)
                change(self.payloads[0])
                self.write_payload(0)
                self.reject_unchanged()

    def test_bad_dates_missing_nontrading_duplicate_and_noncanonical_order_reject(self):
        original = copy.deepcopy(self.payloads[0])
        variants = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[-1])),
                    lambda rows: rows[0].__setitem__(0, "2005-01-08"),
                    lambda rows: rows[0].__setitem__(0, "2005-02-29"),
                    lambda rows: rows[0].__setitem__(0, "2005-1-03"),
                    lambda rows: rows.reverse()]
        for number, change in enumerate(variants):
            with self.subTest(variant=number):
                self.payloads[0] = copy.deepcopy(original)
                change(self.payloads[0]["data"]["sh000852"]["day"])
                self.write_payload(0)
                self.reject_unchanged()

    def test_ohlc_requires_real_positive_finite_and_consistent_values(self):
        original = copy.deepcopy(self.payloads[0])
        variants = [(1, True), (1, None), (1, "NaN"), (1, "Infinity"), (1, ""),
                    (1, "0"), (1, "-1"), (1, "999999"), (2, "999999"), (3, "1"), (4, "999999")]
        for column, value in variants:
            with self.subTest(column=column, value=value):
                self.payloads[0] = copy.deepcopy(original)
                self.payloads[0]["data"]["sh000852"]["day"][0][column] = value
                self.write_payload(0)
                self.reject_unchanged()

    def test_discarded_rows_also_validate_ohlc_and_cross_year_overlap(self):
        original = copy.deepcopy(self.payloads[1])
        for value in ("NaN", "999999", str(float(original["data"]["sh000852"]["day"][0][1]) + 0.25)):
            with self.subTest(value=value):
                self.payloads[1] = copy.deepcopy(original)
                self.payloads[1]["data"]["sh000852"]["day"][0][1] = value
                self.write_payload(1)
                self.reject_unchanged()

    def test_claimed_annual_counts_and_calendar_are_independently_rechecked(self):
        original = copy.deepcopy(self.document)
        for key, value in (("raw_rows", 1), ("window_rows", 1), ("first", "2005-01-04"),
                           ("raw_first", "2005-01-04"), ("expected_calendar_rows", 1),
                           ("discarded_outside_window", 1), ("missing_calendar_dates", ["2005-01-03"])):
            with self.subTest(key=key):
                self.document = copy.deepcopy(original)
                self.document["windows"][0][key] = value
                self.write_manifest()
                self.reject_unchanged()
        self.document = original
        self.write_manifest()
        with self.con:
            self.con.execute("DELETE FROM calendar WHERE date='2005-01-03'")
        self.reject_unchanged()

    def test_legacy_dry_run_never_migrates_and_apply_requires_explicit_upgrade(self):
        path = self.root / "legacy.sqlite"
        legacy = create_legacy(path)
        self.addCleanup(legacy.close)
        with legacy:
            for table, order in TABLES.items():
                if table == "sqlite_sequence":
                    continue
                rows = [tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {order}")]
                if table == "meta":
                    rows = [r for r in rows if r[0] not in ("schema", DATE_CONSTRAINT_KEY)]
                if rows:
                    legacy.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows)
        self.db, self.con = path, legacy
        before, disk = self.snapshot(), DB.sha256_file(path)
        self.assertTrue(self.call()["dry_run"])
        with self.assertRaisesRegex(DB.DbError, "upgrade-date-constraints"):
            self.call(apply=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(path), disk)
        self.assertTrue(upgrade(path, apply=True)["applied"])
        self.assertTrue(self.call(apply=True)["applied"])

    def test_cli_default_is_readonly_and_errors_are_nonzero(self):
        from src.data.__main__ import main
        argv = ["offline-tencent-price", "--db", str(self.db), "--recorded-dir", str(self.recorded)]
        disk, output = DB.sha256_file(self.db), io.StringIO()
        with self.patch_index(), contextlib.redirect_stdout(output):
            self.assertEqual(main(argv), 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertEqual(DB.sha256_file(self.db), disk)
        with self.patch_index(), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(argv + ["--apply"]), 0)
        (self.recorded / self.document["windows"][0]["request"]["file"]).unlink()
        error = io.StringIO()
        with self.patch_index(), contextlib.redirect_stderr(error):
            self.assertEqual(main(argv + ["--apply"]), 1)
        self.assertIn("error", json.loads(error.getvalue()))


if __name__ == "__main__":
    unittest.main()
