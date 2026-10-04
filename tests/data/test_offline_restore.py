"""仅合成临时库及录制响应；不读取服务器原件，不允许联网。"""
import hashlib
import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import tests  # noqa: F401 — 默认真实库测试防线
from src.data import db as DB
from src.data.date_constraints import DATE_CONSTRAINT_KEY, DATE_TRIGGERS, upgrade
from src.data.offline_restore import RestoreError, restore
from src.data.sources import CSI_PERF, parse_csindex_data
from tests.data.test_date_constraints import create_legacy

TABLES = {"meta": "key", "runs": "run_id", "bars": "code, adj, date", "coverage": "run_id, theme_id",
          "requests": "run_id, seq", "update_results": "run_id, seq", "calendar": "date", "universe": "theme_id"}


class OfflineRestore(unittest.TestCase):
    END = date(2026, 9, 30)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "market.sqlite"
        self.recorded = self.root / "recorded"
        self.recorded.mkdir()
        self.con = DB.connect(self.db)
        self.addCleanup(self.con.close)
        self.source_run = DB.start_run(self.con, "backfill", end=self.END, args={"start": "2000-01-01"}, universe_sha256="seed")
        cov = {key: "" for key in DB.COVERAGE_COLUMNS}
        cov.update(theme_id="T01", container="沪深300", code="000300", status="active", error="CSI HTTP 403",
                   exec_code="510300", exec_route="eastmoney_etf", exec_first_date="2026-09-29",
                   exec_last_date="2026-09-30", exec_rows="2", exec_error="keep-execution-note", checked_at="old-check",
                   notes="historical failure, do not discard", price_first_date="2005-01-04")
        other = dict(cov, theme_id="T02", code="000905", exec_code="510500")
        DB.write_coverage(self.con, self.source_run, [cov, other])
        self.con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            ("510300", "raw", "2026-09-29", 1, 2, 1, 2, 3, 4, "eastmoney_etf", "original-exec-time"),
            ("510300", "raw", "2026-09-30", 2, 3, 1, 3, 4, 5, "eastmoney_etf", "original-exec-time")])
        self.con.executemany("INSERT INTO calendar VALUES (?)", [("2005-01-04",), ("2026-09-30",)])
        self.con.execute("INSERT INTO universe VALUES (0, 'T01', ?)", (json.dumps({"theme_id": "T01"}),))
        self.con.commit()
        self.by_year = {2004: [self.row("20041231", 100)],
                        2005: [self.row("20050104", 101), self.row("20050108", 102)],  # 原非交易日不删
                        2006: [self.row("20060103", None)],  # NULL close 也不补造 / 丢弃
                        2026: [self.row("20260930", 103, open=102, high=104, low=101)]}
        requests = []
        for year in range(2000, 2027):
            end = min(date(year, 12, 31), self.END)
            requests.append(self.record(year - 2000, date(year, 1, 1), end,
                                        {"code": "200", "data": self.by_year.get(year, [])}))
        # 探测短窗中重叠日期故意给出不一致价格，证明不会拼入年度序列。
        requests.append(self.record(27, self.END - timedelta(days=45), self.END,
                                    {"code": "200", "data": [self.row("20260930", 999999)]}))
        DB.write_requests(self.con, self.source_run, requests)
        DB.finish_run(self.con, self.source_run)
        for target in ("src.data.http.get", "src.data.http.urlopen", "src.data.sources.fetch_csindex"):
            patcher = mock.patch(target, side_effect=AssertionError("offline restore attempted network"))
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def row(day, close, **kw):
        return {"tradeDate": day, "indexCode": "H00300", "indexNameCnAll": "沪深300全收益指数", "close": close, **kw}

    def record(self, seq, start, end, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        name = f"{seq}.body"
        (self.recorded / name).write_bytes(raw)
        return {"url": CSI_PERF + "?" + urlencode({"indexCode": "H00300", "startDate": start.strftime("%Y%m%d"),
                                                   "endDate": end.strftime("%Y%m%d")}),
                "fetched_at": f"2026-10-02T00:{seq:02d}:00+00:00", "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "file": name, "error": None}

    def snapshot(self):
        return DB.content_sha256(self.con, TABLES)

    def call(self, **kwargs):
        return restore(self.db, self.recorded, self.source_run, **kwargs)

    def change_payload(self, seq, payload):
        raw = json.dumps(payload).encode()
        (self.recorded / f"{seq}.body").write_bytes(raw)
        with self.con:
            self.con.execute("UPDATE requests SET bytes = ?, sha256 = ? WHERE run_id = ? AND seq = ?",
                             (len(raw), hashlib.sha256(raw).hexdigest(), self.source_run, seq))

    def reject_unchanged(self, message, **kwargs):
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaisesRegex(RestoreError, message):
            self.call(apply=True, **kwargs)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_dry_run_is_default_and_byte_for_byte_readonly(self):
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        report = self.call()
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["applied"])
        self.assertEqual((report["rows"], report["rows_to_insert"]), (5, 5))
        self.assertEqual((report["annual_requests"], report["verified_requests"]), (27, 28))
        self.assertEqual(report["excluded_short_window_requests"], [27])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)
        self.assertFalse(list(self.root.glob("*.sqlite-*")))

    def test_cli_requires_explicit_apply(self):
        from src.data.__main__ import main
        args = ["offline-restore", "--db", str(self.db), "--source-run-id", str(self.source_run),
                "--recorded-dir", str(self.recorded)]
        before = DB.sha256_file(self.db)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertEqual(DB.sha256_file(self.db), before)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ["--apply"]), 0)
        self.assertTrue(json.loads(output.getvalue())["applied"])

    def test_legacy_database_requires_explicit_upgrade_before_restore_apply(self):
        # 原 requests / 响应在冻结的旧 schema 中同样可恢复；dry-run 不能顺便迁移。
        legacy_path = self.root / "legacy.sqlite"
        legacy = create_legacy(legacy_path)
        self.addCleanup(legacy.close)
        with legacy:
            for table, order in TABLES.items():
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
        self.assertEqual(self.con.execute("SELECT count(*) FROM bars WHERE code='H00300'").fetchone()[0], 5)
        self.assertTrue(self.call(apply=True)["idempotent"])

    def test_restore_apply_rejects_incomplete_date_constraint_contract_without_repair(self):
        self.con.execute(f"DROP TRIGGER {next(iter(DATE_TRIGGERS))}")
        self.con.commit()
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        with self.assertRaisesRegex(DB.DbError, "upgrade-date-constraints"):
            self.call(apply=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_atomic_apply_preserves_dates_nulls_origin_and_all_protected_data(self):
        old_tables = {table: [tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {order}")]
                      for table, order in TABLES.items()}
        old_cov = dict(self.con.execute("SELECT * FROM coverage_latest WHERE theme_id = 'T01'").fetchone())
        report = self.call(apply=True)
        self.assertTrue(report["applied"])
        self.assertEqual(report["ohlc_missing_rows"], 4)
        self.assertEqual(report["null_close_rows"], 1)
        bars = [dict(r) for r in self.con.execute("SELECT * FROM bars WHERE code = 'H00300' ORDER BY date")]
        self.assertEqual([r["date"] for r in bars], ["2004-12-31", "2005-01-04", "2005-01-08", "2006-01-03", "2026-09-30"])
        self.assertIsNone(bars[3]["close"])
        self.assertIsNone(bars[0]["open"])
        self.assertEqual(bars[-1]["close"], 103)
        self.assertTrue(all(r["source"] == "csi" and r["adj"] == "raw" for r in bars))
        self.assertEqual(bars[0]["fetched_at"], "2026-10-02T00:04:00+00:00")
        self.assertEqual(bars[-1]["fetched_at"], "2026-10-02T00:26:00+00:00")
        cov = dict(self.con.execute("SELECT * FROM coverage_latest WHERE theme_id = 'T01'").fetchone())
        self.assertEqual((cov["series_code"], cov["route_used"], cov["tr_code_used"], cov["price_only"]),
                         ("H00300", "csi", "H00300", "False"))
        self.assertEqual(cov["rows"], "5")
        self.assertEqual(cov["error"], "")
        self.assertTrue(cov["notes"].startswith(old_cov["notes"]))
        for key in [k for k in cov if k.startswith("exec_")] + ["price_first_date", "container", "code", "status"]:
            self.assertEqual(cov[key], old_cov[key])
        for table in ("meta", "requests", "update_results", "calendar", "universe"):
            self.assertEqual([tuple(r) for r in self.con.execute(f"SELECT * FROM {table} ORDER BY {TABLES[table]}")], old_tables[table])
        self.assertEqual([tuple(r) for r in self.con.execute("SELECT * FROM bars WHERE code != 'H00300' ORDER BY code, adj, date")], old_tables["bars"])
        self.assertEqual([tuple(r) for r in self.con.execute("SELECT * FROM coverage WHERE run_id = ? ORDER BY theme_id", (self.source_run,))], old_tables["coverage"])
        self.assertEqual(tuple(self.con.execute("SELECT * FROM runs WHERE run_id = ?", (self.source_run,)).fetchone()), old_tables["runs"][0])
        job = self.con.execute("SELECT * FROM runs WHERE run_id = ?", (report["run_id"],)).fetchone()
        self.assertEqual((job["kind"], job["status"], job["universe_sha256"]), ("backfill", "ok", "seed"))
        args = json.loads(job["args"])
        self.assertTrue(args["offline_restore"])
        self.assertEqual(args["source_run_id"], self.source_run)
        self.assertEqual(len(args["request_refs"]), 28)
        self.assertEqual(args["excluded_short_window_request_seqs"], [27])
        self.assertEqual(self.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_repeated_apply_does_not_add_history_or_touch_bytes(self):
        first = self.call(apply=True)
        before, disk = self.snapshot(), DB.sha256_file(self.db)
        again = self.call(apply=True)
        self.assertTrue(again["idempotent"])
        self.assertFalse(again["changed"])
        self.assertEqual(again["run_id"], first["run_id"])
        self.assertEqual(again["rows_to_insert"], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.db), disk)

    def test_latest_execution_coverage_is_carried_forward(self):
        newer = DB.start_run(self.con, "update", end=self.END)
        cov = dict(self.con.execute("SELECT * FROM coverage_latest WHERE theme_id = 'T01'").fetchone())
        cov.update(exec_rows="9000", exec_error="newer failure", exec_last_date="2026-10-01")
        DB.write_coverage(self.con, newer, [cov])
        self.call(apply=True)
        got = self.con.execute("SELECT * FROM coverage_latest WHERE theme_id = 'T01'").fetchone()
        for key in ("exec_rows", "exec_error", "exec_last_date"):
            self.assertEqual(got[key], cov[key])

    def test_exact_partial_rows_can_be_restored_without_replacement(self):
        with self.con:
            self.con.execute("INSERT INTO bars VALUES ('H00300', 'raw', '2004-12-31', NULL, NULL, NULL, 100, NULL, NULL, 'csi', '2026-10-02T00:04:00+00:00')")
        self.assertEqual(self.call(apply=True)["rows_to_insert"], 4)

    def test_missing_file_fails_closed(self):
        (self.recorded / "10.body").unlink()
        self.reject_unchanged("离线恢复失败")

    def test_missing_year_is_not_filled_from_short_window(self):
        with self.con:
            self.con.execute("DELETE FROM requests WHERE seq = 26")
        self.reject_unchanged("年度请求缺失.*2026")

    def test_short_window_is_also_hash_verified(self):
        path = self.recorded / "27.body"
        path.write_bytes(path.read_bytes().replace(b"999999", b"888888"))
        self.reject_unchanged("sha256")

    def test_bytes_mismatch_rejected_even_when_hash_matches(self):
        with self.con:
            self.con.execute("UPDATE requests SET bytes = bytes + 1 WHERE seq = 4")
        self.reject_unchanged("bytes")

    def test_duplicate_annual_request_rejected(self):
        with self.con:
            self.con.execute("INSERT INTO requests SELECT run_id, 28, url, fetched_at, bytes, sha256, error, file FROM requests WHERE seq = 4")
        self.reject_unchanged("请求重复")

    def test_invalid_window_cannot_be_mislabeled_short_probe(self):
        with self.con:
            self.con.execute("UPDATE requests SET url = replace(url, '20040101', '20040102') WHERE seq = 4")
        self.reject_unchanged("完整年度窗口")

    def test_response_outside_window_rejected_without_silent_clipping(self):
        self.change_payload(4, {"code": "200", "data": [self.row("20050104", 100)]})
        self.reject_unchanged("窗口外日期")

    def test_duplicate_response_date_rejected_without_silent_dedup(self):
        self.change_payload(4, {"code": "200", "data": [self.row("20041231", 100), self.row("20041231", 200)]})
        self.reject_unchanged("重复日期")

    def test_invalid_calendar_date_rejected(self):
        self.change_payload(4, {"code": "200", "data": [self.row("20040230", 100)]})
        self.reject_unchanged("日期非法")

    def test_wrong_code_response_rejected(self):
        self.change_payload(4, {"code": "200", "data": [self.row("20041231", 100, indexCode="000300")]})
        self.reject_unchanged("不是 H00300")

    def test_nonfinite_number_rejected(self):
        self.change_payload(4, {"code": "200", "data": [self.row("20041231", float("inf"))]})
        self.reject_unchanged("非有限")

    def test_existing_conflicting_price_source_or_time_rejected(self):
        for source, price, at in (("csi", 999, "2026-10-02T00:04:00+00:00"),
                                  ("eastmoney_index", 100, "2026-10-02T00:04:00+00:00"),
                                  ("csi", 100, "2026-10-03T00:04:00+00:00")):
            with self.subTest(source=source, price=price, at=at):
                with self.con:
                    self.con.execute("DELETE FROM bars WHERE code = 'H00300'")
                    self.con.execute("INSERT INTO bars VALUES ('H00300', 'raw', '2004-12-31', NULL, NULL, NULL, ?, NULL, NULL, ?, ?)", (price, source, at))
                self.reject_unchanged("拒绝覆盖")

    def test_extra_existing_date_rejected(self):
        with self.con:
            self.con.execute("INSERT INTO bars VALUES ('H00300', 'raw', '2004-12-30', NULL, NULL, NULL, 99, NULL, NULL, 'csi', 'old')")
        self.reject_unchanged("拒绝覆盖")

    def test_coverage_insert_failure_rolls_back_new_run_and_all_bars(self):
        self.con.execute("CREATE TRIGGER fail_restore_coverage BEFORE INSERT ON coverage WHEN NEW.run_id != 1 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        self.reject_unchanged("synthetic failure")

    def test_mid_bar_insert_failure_rolls_back_earlier_bars_and_run(self):
        self.con.execute("CREATE TRIGGER fail_restore_bars BEFORE INSERT ON bars WHEN NEW.date = '2005-01-08' BEGIN SELECT RAISE(ABORT, 'mid insert failure'); END")
        self.reject_unchanged("mid insert failure")

    def test_missing_coverage_fails_closed(self):
        with self.con:
            self.con.execute("DELETE FROM coverage WHERE theme_id = 'T01'")
        self.reject_unchanged("缺少现有 T01")

    def test_missing_source_job_and_missing_database_do_not_create_state(self):
        before = self.snapshot()
        with self.assertRaisesRegex(RestoreError, "source_run_id"):
            restore(self.db, self.recorded, 999, apply=True)
        absent = self.root / "absent.sqlite"
        with self.assertRaisesRegex(RestoreError, "行情库不存在"):
            restore(absent, self.recorded, self.source_run, apply=True)
        self.assertFalse(absent.exists())
        self.assertEqual(self.snapshot(), before)

    def test_path_traversal_and_symlink_escape_rejected(self):
        with self.con:
            self.con.execute("UPDATE requests SET file = '../outside.body' WHERE seq = 4")
        self.reject_unchanged("安全的原响应")
        with self.con:
            self.con.execute("UPDATE requests SET file = '4.body' WHERE seq = 4")
        path = self.recorded / "4.body"
        outside = self.root / "outside.body"
        path.rename(outside)
        path.symlink_to(outside)
        self.reject_unchanged("不在 recorded")

    def test_leading_business_error_retains_warning_and_later_error_blocks(self):
        self.change_payload(0, {"code": "404", "data": None})
        self.assertIn("起点可能被截短", self.call()["warnings"][0])
        self.change_payload(25, {"code": "403", "data": None})
        self.reject_unchanged("业务错误")

    def test_http_error_request_with_existing_file_cannot_restore(self):
        with self.con:
            self.con.execute("UPDATE requests SET error = 'HTTP 403' WHERE seq = 4")
        self.reject_unchanged("请求错误")

    def test_probe_source_run_is_supported(self):
        with self.con:
            self.con.execute("UPDATE runs SET kind = 'probe' WHERE run_id = ?", (self.source_run,))
        self.assertTrue(self.call(apply=True)["applied"])

    def test_incomplete_source_job_rejected(self):
        with self.con:
            self.con.execute("UPDATE runs SET status = 'running' WHERE run_id = ?", (self.source_run,))
        self.reject_unchanged("尚未成功结束")

    def test_later_source_start_cannot_shorten_recovery(self):
        with self.con:
            self.con.execute("UPDATE runs SET args = ? WHERE run_id = ?", (json.dumps({"start": "2005-01-01"}), self.source_run))
        self.reject_unchanged("start=2000-01-01")

    def test_shared_parser_can_preserve_null_close_without_changing_online_default(self):
        data = [self.row("20260930", None, open=1)]
        self.assertIsNone(parse_csindex_data(data).rows[0])
        restored = parse_csindex_data(data, preserve_null_close=True).rows[0]
        self.assertEqual(restored["date"], "2026-09-30")
        self.assertEqual(restored["open"], 1)
        self.assertIsNone(restored["close"])


if __name__ == "__main__":
    unittest.main()
