"""三个年末缺日的合成离线证据；不读取正式库、服务器原件或执行研究。"""
import contextlib
import copy
import hashlib
import io
import json
import shutil
import unittest
from urllib.parse import urlencode

import tests  # noqa: F401 — 默认真实库测试防线
from src.data import db as DB
from src.data.date_constraints import DATE_CONSTRAINT_KEY, DATE_TRIGGERS, upgrade
from src.data.offline_restore import RestoreError, restore
from src.data.offline_supplement import supplement
from src.data.sources import CSI_PERF
from tests.data import test_offline_restore as annual_fixture
from tests.data.test_date_constraints import create_legacy


TARGETS = ("2008-12-31", "2009-12-31", "2010-12-31")


class OfflineSupplement(unittest.TestCase):
    def setUp(self):
        # 组合复用年度证据，不能继承 TestCase 导致同一组年度测试重复运行。
        self.annual = annual_fixture.OfflineRestore()
        self.addCleanup(self.annual.doCleanups)
        self.annual.setUp()
        self.root, self.db, self.con = self.annual.root, self.annual.db, self.annual.con
        self.annual.call(apply=True)
        self.recorded = self.root / "yearends"
        self.recorded.mkdir()
        self.manifest = self.recorded / "manifest.json"
        self.document = {"format": "h00300-year-end-v1", "requests": []}
        self.payloads = []
        for i, day in enumerate(TARGETS):
            year = day[:4]
            target = self.annual.row(day.replace("-", ""), 200 + i,
                                     tradingVol=30 + i, tradingValue=40 + i)
            if i == 1:
                target.update(open="--", high=None, low="")
            if i == 2:
                target.update(open="-", high="", low=None)
            # 同一响应里的邻日只作证据，不能扩大本轮补录范围。
            payload = {"code": "200", "data": [self.annual.row(year + "1230", 190 + i), target]}
            self.payloads.append(payload)
            self.document["requests"].append({
                "url": CSI_PERF + "?" + urlencode({"indexCode": "H00300", "startDate": year + "1220",
                                                    "endDate": year + "1231"}),
                "file": f"year-end-{year}.body", "fetched_at": f"2026-10-02T01:0{i}:00+00:00",
                "error": None,
            })
            self.write_payload(i, payload)
        self.write_manifest()

    def write_manifest(self, document=None):
        self.manifest.write_text(json.dumps(self.document if document is None else document,
                                           ensure_ascii=False, indent=2), encoding="utf-8")

    def write_payload(self, i, payload):
        entry = self.document["requests"][i]
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        (self.recorded / entry["file"]).write_bytes(raw)
        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write_manifest()

    def call(self, **kwargs):
        return supplement(self.db, self.manifest, **kwargs)

    def snapshot(self):
        return DB.content_sha256(self.con, dict(annual_fixture.TABLES, sqlite_sequence="name"))

    def reject_unchanged(self, **kwargs):
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaises(RestoreError):
            self.call(apply=True, **kwargs)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def reject_annual_unchanged(self):
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaises(RestoreError):
            restore(self.db, self.annual.recorded, self.annual.source_run, apply=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_default_dry_run_and_explicit_root_are_byte_for_byte_readonly(self):
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        report = self.call()
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["rows_to_insert"], 3)
        relocated = self.root / "manifest-only.json"
        relocated.write_bytes(self.manifest.read_bytes())
        self.assertEqual(supplement(self.db, relocated, recorded_dir=self.recorded)["rows_to_insert"], 3)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)
        self.assertFalse(list(self.root.glob("*.sqlite-*")))

    def test_apply_only_three_targets_preserves_nulls_origin_and_history(self):
        old = {table: [tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {order}")]
               for table, order in annual_fixture.TABLES.items()}
        old_cov = dict(self.con.execute("SELECT * FROM coverage_latest WHERE theme_id='T01'").fetchone())
        report = self.call(apply=True)
        self.assertTrue(report["applied"])
        self.assertEqual(report["rows_to_insert"], 3)
        bars = [dict(r) for r in self.con.execute(
            "SELECT * FROM bars WHERE code='H00300' AND date BETWEEN '2008-01-01' AND '2010-12-31' ORDER BY date")]
        self.assertEqual([r["date"] for r in bars], list(TARGETS))
        for i, row in enumerate(bars):
            self.assertEqual((row["open"], row["high"], row["low"]), (None, None, None))
            self.assertEqual((row["close"], row["volume"], row["amount"]), (200 + i, 30 + i, 40 + i))
            self.assertEqual((row["source"], row["adj"]), ("csi", "raw"))
            self.assertEqual(row["fetched_at"], self.document["requests"][i]["fetched_at"])
        for table in ("meta", "calendar", "universe", "update_results"):
            self.assertEqual([tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {annual_fixture.TABLES[table]}")], old[table])
        for table in ("runs", "requests", "coverage"):
            self.assertEqual([tuple(r) for r in self.con.execute(
                f"SELECT * FROM {table} WHERE run_id < ? ORDER BY {annual_fixture.TABLES[table]}", (report["run_id"],))], old[table])
        current = [tuple(r) for r in self.con.execute("SELECT * FROM bars ORDER BY code,adj,date")]
        self.assertTrue(all(row in current for row in old["bars"]))
        cov = dict(self.con.execute("SELECT * FROM coverage_latest WHERE theme_id='T01'").fetchone())
        self.assertEqual(cov["rows"], "8")
        self.assertEqual(cov["ohlc_missing_rows"], "7")
        for key in [k for k in cov if k.startswith("exec_")] + ["price_first_date", "code", "container", "status"]:
            self.assertEqual(cov[key], old_cov[key])
        self.assertEqual(self.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_audit_embeds_exact_evidence_and_all_request_metadata(self):
        report = self.call(apply=True)
        job = self.con.execute("SELECT * FROM runs WHERE run_id=?", (report["run_id"],)).fetchone()
        self.assertEqual((job["kind"], job["status"]), ("backfill", "ok"))
        args = json.loads(job["args"])
        self.assertIs(args["offline_supplement"], True)
        self.assertEqual(args["format"], "h00300-year-end-v1")
        self.assertEqual(args["manifest_sha256"], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(args["inserted_dates"], list(TARGETS))
        self.assertEqual(args["preexisting_exact_dates"], [])
        self.assertEqual(args["evidence"]["manifest_text"], self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(args["evidence"]["response_texts"], [
            (self.recorded / request["file"]).read_text(encoding="utf-8") for request in self.document["requests"]])
        records = self.con.execute("SELECT * FROM requests WHERE run_id=? ORDER BY seq", (report["run_id"],)).fetchall()
        self.assertEqual(len(records), 3)
        for i, (record, expected) in enumerate(zip(records, self.document["requests"])):
            self.assertEqual(record["seq"], i)
            for key, value in expected.items():
                self.assertEqual(record[key], value)

    def test_repeated_apply_adds_no_audit_or_bytes(self):
        first = self.call(apply=True)
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        again = self.call(apply=True)
        self.assertTrue(again["idempotent"])
        self.assertFalse(again["changed"])
        self.assertEqual(again["run_id"], first["run_id"])
        self.assertEqual(again["rows_to_insert"], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_exact_existing_target_is_audited_without_replacement(self):
        with self.con:
            self.con.execute("INSERT INTO bars VALUES ('H00300','raw',?,NULL,NULL,NULL,200,30,40,'csi',?)",
                             (TARGETS[0], self.document["requests"][0]["fetched_at"]))
        before = tuple(self.con.execute("SELECT * FROM bars WHERE date=?", (TARGETS[0],)).fetchone())
        report = self.call(apply=True)
        self.assertEqual(report["rows_to_insert"], 2)
        self.assertEqual(tuple(self.con.execute("SELECT * FROM bars WHERE date=?", (TARGETS[0],)).fetchone()), before)
        args = json.loads(self.con.execute("SELECT args FROM runs WHERE run_id=?", (report["run_id"],)).fetchone()[0])
        self.assertEqual(args["preexisting_exact_dates"], [TARGETS[0]])
        self.assertEqual(args["inserted_dates"], list(TARGETS[1:]))
        self.assertTrue(self.annual.call(apply=True)["idempotent"])

    def test_cli_default_apply_and_failure_exit_status(self):
        from src.data.__main__ import main
        argv = ["offline-supplement", "--db", str(self.db), "--manifest", str(self.manifest)]
        disk = DB.sha256_file(self.db)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(argv), 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertEqual(DB.sha256_file(self.db), disk)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(argv + ["--apply"]), 0)
        self.manifest.write_text("{}", encoding="utf-8")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(argv + ["--apply"]), 1)
        self.assertIn("error", json.loads(error.getvalue()))

    def test_manifest_requires_exact_format_and_three_distinct_target_windows(self):
        variants = [[], {}, {**self.document, "format": "unknown"}, {**self.document, "unknown": 1},
                    {**self.document, "requests": self.document["requests"][:2]},
                    {**self.document, "requests": self.document["requests"] + [self.document["requests"][0]]},
                    {**self.document, "requests": [self.document["requests"][0]] * 3}]
        for document in variants:
            with self.subTest(document=document):
                self.write_manifest(document)
                self.reject_unchanged()

    def test_request_source_query_and_window_are_strict(self):
        original = self.document["requests"][0]["url"]
        urls = [original.replace("https://", "http://"), original.replace("www.csindex.com.cn", "example.org"),
                original.replace("index-perf", "index-perf-other"), original + "#fragment",
                original + "&indexCode=H00300", original + "&unknown=1", original.replace("H00300", "000300"),
                original.replace("20081220", "20080101"), original.replace("20081231", "20081230"),
                original.replace("20081220", "20090101"), original.replace("20081220", "20081301"),
                original.replace("20081231", "20111231"), "https://["]
        for url in urls:
            with self.subTest(url=url):
                self.document["requests"][0]["url"] = url
                self.write_manifest()
                self.reject_unchanged()

    def test_request_hash_length_required_fields_and_error_are_checked(self):
        original = copy.deepcopy(self.document)
        changes = [("sha256", "0" * 64), ("sha256", None), ("bytes", 1), ("bytes", True),
                   ("bytes", "100"), ("error", "HTTP 403"), ("file", ""), ("file", None)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.document = copy.deepcopy(original)
                self.document["requests"][0][key] = value
                self.write_manifest()
                self.reject_unchanged()
        for key in ("url", "sha256", "bytes", "file", "fetched_at"):
            with self.subTest(missing=key):
                self.document = copy.deepcopy(original)
                del self.document["requests"][0][key]
                self.write_manifest()
                self.reject_unchanged()

    def test_changed_bytes_missing_file_and_unsafe_path_fail_closed(self):
        entry = self.document["requests"][0]
        path = self.recorded / entry["file"]
        original = path.read_bytes()
        path.write_bytes(original.replace(b"200", b"201", 1))
        self.reject_unchanged()
        path.unlink()
        self.reject_unchanged()
        outside = self.root / "outside.body"
        outside.write_bytes(original)
        path.symlink_to(outside)
        self.reject_unchanged()
        for filename in ("../outside.body", str(outside)):
            entry["file"] = filename
            self.write_manifest()
            self.reject_unchanged()

    def test_fetch_time_requires_timezone_past_and_target_close(self):
        for value in (None, "", "not-a-time", "2026-10-02T00:00:00", "2999-01-01T00:00:00+00:00",
                      "2026-10-02T01:00:00+00:99", "2026-10-02T01:00:00-00:99",
                      "2026-10-02T01:00:00+24:00",
                      "2008-12-31T15:29:59+08:00", "2008-12-30T23:59:59+08:00"):
            with self.subTest(value=value):
                self.document["requests"][0]["fetched_at"] = value
                self.write_manifest()
                self.reject_unchanged()

    def test_fetch_time_at_existing_availability_boundary_preserves_offset(self):
        # 仓库国内日线沿用 15:30 可用边界，包含收盘后的缓冲，并非实际交易收盘时刻。
        self.document["requests"][0]["fetched_at"] = "2008-12-31T15:30:00+08:00"
        self.write_manifest()
        self.call(apply=True)
        self.assertEqual(self.con.execute("SELECT fetched_at FROM bars WHERE date=?", (TARGETS[0],)).fetchone()[0],
                         "2008-12-31T15:30:00+08:00")

    def test_response_envelope_dates_duplicates_and_codes_are_validated(self):
        valid = self.payloads[0]["data"][-1]
        variants = [[], {"code": "403", "data": [valid]}, {"code": "200", "data": None},
                    {"code": "200", "data": {}}, {"code": "200", "data": []},
                    {"code": "200", "data": [valid, valid]}, {"code": "200", "data": [None]}]
        for key, value in (("tradeDate", "2008-12-31"), ("tradeDate", "20081232"),
                           ("tradeDate", "20080230"), ("tradeDate", "20090101"),
                           ("indexCode", "000300"), ("indexCode", None), ("indexCode", "")):
            variants.append({"code": "200", "data": [{**valid, key: value}]})
        missing_code = dict(valid)
        del missing_code["indexCode"]
        variants.append({"code": "200", "data": [missing_code]})
        # 邻日也必须通过日期 / 指数 / 重复校验，不能因为不入库就忽略。
        variants.append({"code": "200", "data": [valid, self.annual.row("20090101", 1)]})
        variants.append({"code": "200", "data": [valid, self.annual.row("20081230", 1, indexCode="000300")]})
        for payload in variants:
            with self.subTest(payload=payload):
                self.write_payload(0, payload)
                self.reject_unchanged()

    def test_positive_finite_close_and_absent_ohl_cannot_be_fabricated(self):
        target = self.payloads[0]["data"][-1]
        for value in (None, "", "--", "NaN", float("nan"), float("inf"), -float("inf"), 0, -1, True):
            with self.subTest(close=value):
                self.write_payload(0, {"code": "200", "data": [{**target, "close": value}]})
                self.reject_unchanged()
        for key in ("open", "high", "low"):
            for value in (1, 0, -1, "NaN", float("nan"), "bad", True):
                with self.subTest(key=key, value=value):
                    self.write_payload(0, {"code": "200", "data": [{**target, key: value}]})
                    self.reject_unchanged()
        for key in ("tradingVol", "tradingValue"):
            for value in ("bad", float("nan"), float("inf"), True):
                with self.subTest(key=key, value=value):
                    self.write_payload(0, {"code": "200", "data": [{**target, key: value}]})
                    self.reject_unchanged()

    def test_evidence_requires_utf8_and_rejects_ambiguous_duplicate_json_keys(self):
        original = self.manifest.read_bytes()
        for raw in (b"\xff", original.replace(b'"format":', b'"format":"h00300-year-end-v1","format":', 1)):
            with self.subTest(raw=raw):
                self.manifest.write_bytes(raw)
                self.reject_unchanged()
        self.manifest.write_bytes(original)
        entry = self.document["requests"][0]
        path = self.recorded / entry["file"]
        raw = path.read_bytes()
        for changed in (b"\xff", raw.replace(b'"close":', b'"close":999,"close":', 1)):
            with self.subTest(raw=changed):
                path.write_bytes(changed)
                entry.update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
                self.write_manifest()
                self.reject_unchanged()

    def test_existing_target_conflicts_never_overwrite(self):
        for close, volume, fetched_at, opening in ((999, 30, self.document["requests"][0]["fetched_at"], None),
                                                  (200, 31, self.document["requests"][0]["fetched_at"], None),
                                                  (200, 30, "2026-10-01T00:00:00+00:00", None),
                                                  (200, 30, self.document["requests"][0]["fetched_at"], 199)):
            with self.subTest(close=close, volume=volume, fetched_at=fetched_at, opening=opening):
                with self.con:
                    self.con.execute("DELETE FROM bars WHERE code='H00300' AND date=?", (TARGETS[0],))
                    self.con.execute("INSERT INTO bars VALUES ('H00300','raw',?,?,NULL,NULL,?,?,40,'csi',?)",
                                     (TARGETS[0], opening, close, volume, fetched_at))
                self.reject_unchanged()

    def test_coverage_contract_and_execution_reference_fail_closed(self):
        baseline = self.con.execute("SELECT run_id FROM coverage_latest WHERE theme_id='T01'").fetchone()[0]
        for key, value in (("series_code", "000300"), ("series_adj", "hfq"), ("route_used", "other"),
                           ("tr_code_used", "000300"), ("exec_code", "H00300")):
            with self.subTest(key=key):
                old = self.con.execute(f"SELECT {key} FROM coverage WHERE run_id=? AND theme_id='T01'", (baseline,)).fetchone()[0]
                with self.con:
                    self.con.execute(f"UPDATE coverage SET {key}=? WHERE run_id=? AND theme_id='T01'", (value, baseline))
                self.reject_unchanged()
                with self.con:
                    self.con.execute(f"UPDATE coverage SET {key}=? WHERE run_id=? AND theme_id='T01'", (old, baseline))
        with self.con:
            self.con.execute("DELETE FROM coverage WHERE theme_id='T01'")
        self.reject_unchanged()

    def test_failures_after_partial_writes_roll_back_entire_transaction(self):
        for table, condition in (("bars", "NEW.date='2009-12-31'"), ("requests", "NEW.seq=1"),
                                 ("coverage", "NEW.theme_id='T01'")):
            with self.subTest(table=table):
                self.con.execute(f"CREATE TRIGGER fail_supplement BEFORE INSERT ON {table} WHEN {condition} "
                                 "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
                self.con.commit()
                self.reject_unchanged()
                self.con.execute("DROP TRIGGER fail_supplement")
                self.con.commit()

    def test_old_date_contract_requires_explicit_upgrade_and_dry_run_never_migrates(self):
        legacy_path = self.root / "legacy.sqlite"
        legacy = create_legacy(legacy_path)
        self.addCleanup(legacy.close)
        with legacy:
            for table, order in annual_fixture.TABLES.items():
                rows = [tuple(row) for row in self.con.execute(f"SELECT * FROM {table} ORDER BY {order}")]
                if table == "meta":
                    rows = [row for row in rows if row[0] not in ("schema", DATE_CONSTRAINT_KEY)]
                if rows:
                    legacy.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows)
        self.db, self.con = legacy_path, legacy
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        self.assertTrue(self.call()["dry_run"])
        with self.assertRaisesRegex(DB.DbError, "upgrade-date-constraints"):
            self.call(apply=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)
        self.assertTrue(upgrade(self.db, apply=True)["applied"])
        self.assertTrue(self.call(apply=True)["applied"])

    def test_incomplete_date_contract_is_not_silently_repaired(self):
        self.con.execute(f"DROP TRIGGER {next(iter(DATE_TRIGGERS))}")
        self.con.commit()
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaisesRegex(DB.DbError, "upgrade-date-constraints"):
            self.call(apply=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_annual_rerun_accepts_only_audited_targets_without_original_supplement_files(self):
        supplemental = self.call(apply=True)
        shutil.rmtree(self.recorded)
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        report = self.annual.call(apply=True)
        self.assertTrue(report["idempotent"])
        self.assertEqual(report["rows"], 8)
        self.assertEqual(report["annual_rows"], 5)
        self.assertEqual(report["retained_supplement_dates"], list(TARGETS))
        self.assertEqual(report["supplement_run_ids"], [supplemental["run_id"]])
        self.assertEqual(report["rows_to_insert"], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_annual_rerun_rejects_unaudited_target_and_unrelated_extra(self):
        with self.con:
            self.con.execute("INSERT INTO bars VALUES ('H00300','raw',?,NULL,NULL,NULL,200,30,40,'csi',?)",
                             (TARGETS[0], self.document["requests"][0]["fetched_at"]))
        self.reject_annual_unchanged()
        self.call(apply=True)
        with self.con:
            self.con.execute("INSERT INTO bars VALUES ('H00300','raw','2008-12-30',NULL,NULL,NULL,190,NULL,NULL,'csi','unproven')")
        self.reject_annual_unchanged()

    def test_supplement_cannot_mask_changed_annual_rows(self):
        self.call(apply=True)
        with self.con:
            self.con.execute("DELETE FROM bars WHERE code='H00300' AND date='2004-12-31'")
            self.con.execute("INSERT INTO bars VALUES ('H00300','raw','2004-12-31',NULL,NULL,NULL,999,NULL,NULL,'csi','2026-10-02T00:04:00+00:00')")
        self.reject_annual_unchanged()

    def test_annual_restores_its_missing_rows_while_preserving_audited_supplement(self):
        self.call(apply=True)
        supplemented = [tuple(row) for row in self.con.execute(
            "SELECT * FROM bars WHERE code='H00300' AND date IN (?,?,?) ORDER BY date", TARGETS)]
        with self.con:
            self.con.execute("DELETE FROM bars WHERE code='H00300' AND date='2004-12-31'")
        report = self.annual.call(apply=True)
        self.assertEqual(report["rows_to_insert"], 1)
        self.assertEqual(report["rows"], 8)
        self.assertEqual([tuple(row) for row in self.con.execute(
            "SELECT * FROM bars WHERE code='H00300' AND date IN (?,?,?) ORDER BY date", TARGETS)], supplemented)
        self.assertTrue(self.annual.call(apply=True)["idempotent"])

    def test_annual_does_not_reinsert_deleted_supplement_target(self):
        first = self.call(apply=True)
        with self.con:
            self.con.execute("DELETE FROM bars WHERE code='H00300' AND date=?", (TARGETS[0],))
        self.annual.call(apply=True)
        self.assertIsNone(self.con.execute("SELECT * FROM bars WHERE code='H00300' AND date=?", (TARGETS[0],)).fetchone())
        report = self.call(apply=True)
        self.assertEqual(report["rows_to_insert"], 1)
        self.assertNotEqual(report["run_id"], first["run_id"])
        self.assertEqual(self.con.execute("SELECT count(*) FROM bars WHERE code='H00300'").fetchone()[0], 8)

    def test_annual_revalidates_audit_args_embedded_bytes_and_success_state(self):
        report = self.call(apply=True)
        run_id = report["run_id"]
        original = self.con.execute("SELECT args FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
        args = json.loads(original)
        variants = []
        for key, value in (("offline_supplement", False), ("format", "unknown"), ("manifest_sha256", "0" * 64),
                           ("inserted_dates", list(TARGETS[:2])), ("preexisting_exact_dates", [TARGETS[0]])):
            variants.append({**args, key: value})
        broken_manifest = copy.deepcopy(args)
        broken_manifest["evidence"]["manifest_text"] += " "
        variants.append(broken_manifest)
        broken_raw = copy.deepcopy(args)
        broken_raw["evidence"]["response_texts"][0] += " "
        variants.append(broken_raw)
        invalid_utf8 = copy.deepcopy(args)
        invalid_utf8["evidence"]["response_texts"][0] = "\ud800"
        variants.append(invalid_utf8)
        for value in variants:
            with self.subTest(value=value):
                with self.con:
                    self.con.execute("UPDATE runs SET args=? WHERE run_id=?", (json.dumps(value), run_id))
                self.reject_annual_unchanged()
        with self.con:
            self.con.execute("UPDATE runs SET args=?,status='running' WHERE run_id=?", (original, run_id))
        self.reject_annual_unchanged()

    def test_annual_revalidates_every_request_field_not_just_hash(self):
        report = self.call(apply=True)
        run_id = report["run_id"]
        original = dict(self.con.execute("SELECT * FROM requests WHERE run_id=? AND seq=0", (run_id,)).fetchone())
        for key, value in (("url", "https://example.org/untrusted"), ("fetched_at", "2026-10-01T00:00:00+00:00"),
                           ("bytes", original["bytes"] + 1), ("sha256", "0" * 64), ("error", "HTTP 403"),
                           ("file", "different.body")):
            with self.subTest(key=key):
                with self.con:
                    self.con.execute(f"UPDATE requests SET {key}=? WHERE run_id=? AND seq=0", (value, run_id))
                self.reject_annual_unchanged()
                with self.con:
                    self.con.execute(f"UPDATE requests SET {key}=? WHERE run_id=? AND seq=0", (original[key], run_id))
        with self.con:
            self.con.execute("DELETE FROM requests WHERE run_id=? AND seq=0", (run_id,))
        self.reject_annual_unchanged()

    def test_annual_revalidates_supplement_bar_source_values_and_timestamp(self):
        self.call(apply=True)
        row = dict(self.con.execute("SELECT * FROM bars WHERE code='H00300' AND date=?", (TARGETS[0],)).fetchone())
        for key, value in (("close", 999), ("open", 198), ("volume", 31), ("amount", 41), ("fetched_at", "wrong-time")):
            with self.subTest(key=key):
                changed = {**row, key: value}
                with self.con:
                    self.con.execute("DELETE FROM bars WHERE code='H00300' AND date=?", (TARGETS[0],))
                    self.con.execute(f"INSERT INTO bars ({','.join(changed)}) VALUES ({','.join('?' for _ in changed)})", tuple(changed.values()))
                self.reject_annual_unchanged()


if __name__ == "__main__":
    unittest.main()
