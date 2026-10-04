"""跨 SQLite 版本的数据库日期约束；仅操作合成临时新库 / 冻结的 market-v1 旧库。"""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401 — 默认真实库测试防线
from src.data import db as DB
from src.data.date_constraints import (
    DATE_CONSTRAINT_KEY, DATE_CONSTRAINT_VERSION, DATE_TRIGGERS, UpgradeError, upgrade,
)


LEGACY_SCHEMA = (Path(__file__).parent / "fixtures" / "market-v1-ab64650.sql").read_text(encoding="utf-8")
TABLES = {"runs": "run_id", "bars": "code, adj, date", "coverage": "run_id, theme_id",
          "requests": "run_id, seq", "update_results": "run_id, seq", "calendar": "date",
          "universe": "theme_id", "sqlite_sequence": "name"}
INVALID_DATES = (
    "", "2026-2-03", "2026-02-3", "20260203", "2026/02/03", "2026-02-30", "2026-04-31",
    "1900-02-29", "2100-02-29", "0000-01-01", "10000-01-01", "-001-01-01", "2026-00-01",
    "2026-13-01", "2026-01-00", "2026-01-32", "2026-02-03 ", " 2026-02-03",
    "2026-02-03T00:00:00", "２０２６-02-03", "2026-02-03\x00", "2026-02-03\x00ignored",
    b"2026-02-03", 20260203, 2451544.5,
)


def create_legacy(path):
    """不调用当前 schema，保证迁移测试实际从 ab64650 的旧 CHECK 开始。"""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(LEGACY_SCHEMA)
    con.execute("INSERT INTO meta VALUES ('schema', 'market-v1')")
    con.commit()
    return con


def schema_rows(con):
    return [tuple(row) for row in con.execute(
        "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master ORDER BY type, name")]


class DateConstraints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def database(self, legacy=False):
        path = self.root / ("legacy.sqlite" if legacy else "new.sqlite")
        con = create_legacy(path) if legacy else DB.connect(path)
        self.addCleanup(con.close)
        return path, con

    def test_direct_sql_rejects_invalid_dates_in_all_write_forms(self):
        # 不依赖 Python 日期转换：普通 sqlite3 连接也必须拒绝 INSERT/UPDATE/REPLACE/UPSERT。
        statements = {
            "bars": (
                "INSERT INTO bars VALUES ('H00300','raw',?,NULL,NULL,NULL,100,NULL,NULL,'csi','original')",
                "UPDATE bars SET date=? WHERE code='H00300'",
                "INSERT OR REPLACE INTO bars VALUES ('H00300','raw',?,NULL,NULL,NULL,100,NULL,NULL,'csi','original')",
                "INSERT INTO bars VALUES ('H00300','raw','2026-02-03',NULL,NULL,NULL,100,NULL,NULL,'csi','original') "
                "ON CONFLICT(code,adj,date) DO UPDATE SET date=?",
            ),
            "calendar": (
                "INSERT INTO calendar VALUES (?)", "UPDATE calendar SET date=?",
                "INSERT OR REPLACE INTO calendar VALUES (?)",
                "INSERT INTO calendar VALUES ('2026-02-03') ON CONFLICT(date) DO UPDATE SET date=?",
            ),
            "runs": (
                "INSERT INTO runs(kind,started_at,end_date) VALUES ('backfill','original',?)",
                "UPDATE runs SET end_date=? WHERE run_id=1",
                "INSERT OR REPLACE INTO runs(run_id,kind,started_at,end_date) VALUES (1,'backfill','original',?)",
                "INSERT INTO runs(run_id,kind,started_at,end_date) VALUES (1,'backfill','original','2026-02-03') "
                "ON CONFLICT(run_id) DO UPDATE SET end_date=?",
            ),
        }
        for legacy in (False, True):
            path, con = self.database(legacy)
            if legacy:
                upgrade(path, apply=True)
            with con:
                con.execute(statements["bars"][0], ("2026-02-03",))
                con.execute(statements["calendar"][0], ("2026-02-03",))
                con.execute(statements["runs"][0], ("2026-02-03",))
            for table, commands in statements.items():
                values = INVALID_DATES + (() if table == "runs" else (None,))
                if table == "calendar":
                    values += ("2026-10-03", "2026-10-04")
                for command in commands:
                    for value in values:
                        with self.subTest(legacy=legacy, table=table, command=command, value=value):
                            with self.assertRaises(sqlite3.IntegrityError), con:
                                con.execute(command, (value,))
                self.assertEqual(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 1)

    def test_valid_leap_days_boundaries_nullable_runs_and_raw_nontrading_bars(self):
        valid = ("0001-01-01", "1900-02-28", "2000-02-29", "2024-02-29", "2100-02-28", "2400-02-29", "9999-12-31")
        for legacy in (False, True):
            path, con = self.database(legacy)
            if legacy:
                upgrade(path, apply=True)
            with con:
                for day in valid + ("2026-10-03", "2026-10-04"):
                    con.execute("INSERT INTO bars VALUES ('H00300','raw',?,NULL,NULL,NULL,NULL,NULL,NULL,'csi','original')", (day,))
                    con.execute("INSERT INTO runs(kind,started_at,end_date) VALUES ('backfill','original',?)", (day,))
                con.execute("INSERT INTO runs(kind,started_at,end_date) VALUES ('probe','original',NULL)")
                con.execute("UPDATE runs SET end_date=NULL WHERE run_id=1")
                con.executemany("INSERT INTO calendar VALUES (?)", [(day,) for day in ("0001-01-01", "2000-02-29", "2024-02-29", "2400-02-29", "9999-12-31")])
                con.execute("UPDATE calendar SET date='1904-02-29' WHERE date='2000-02-29'")
            self.assertEqual(con.execute("SELECT count(*) FROM bars WHERE open IS NULL AND close IS NULL").fetchone()[0], len(valid) + 2)
            self.assertEqual(con.execute("SELECT count(*) FROM runs WHERE end_date IS NULL").fetchone()[0], 2)
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_new_database_has_revision_and_all_persistent_triggers(self):
        path, con = self.database()
        self.assertEqual(con.execute("SELECT value FROM meta WHERE key=?", (DATE_CONSTRAINT_KEY,)).fetchone()[0], DATE_CONSTRAINT_VERSION)
        have = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertEqual(len(DATE_TRIGGERS), 6)
        self.assertTrue(set(DATE_TRIGGERS).issubset(have))
        con.close()
        # 再开一个普通连接，约束仍有效，不需要注册 Python UDF。
        with sqlite3.connect(path) as direct, self.assertRaises(sqlite3.IntegrityError):
            direct.execute("INSERT INTO calendar VALUES ('2026-02-30')")


class UpgradeDateConstraints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "old.sqlite"
        self.con = create_legacy(self.path)
        self.addCleanup(self.con.close)
        with self.con:
            self.con.executemany("INSERT INTO runs(run_id,kind,started_at,finished_at,end_date,args,status) VALUES (?,'backfill','start','finish',?,?,'ok')",
                                 [(1, "2000-02-29", '{"historical":true}'), (33, None, '{}')])
            self.con.execute("INSERT INTO bars VALUES ('H00300','raw','2026-10-03',NULL,NULL,NULL,NULL,NULL,NULL,'csi','original-fetch-time')")
            self.con.execute("INSERT INTO calendar VALUES ('2000-02-29')")
            self.con.execute("INSERT INTO coverage(run_id,theme_id,series_code,exec_code,notes) VALUES (1,'T01','H00300','510300','historical coverage')")
            self.con.execute("INSERT INTO requests VALUES (1,0,'recorded-url','original-request-time',3,'hash',NULL,'0.body')")
            self.con.execute("INSERT INTO update_results(run_id,seq,theme_id,kind,code,adj,route,ok,last_date) VALUES (1,0,'T01','research','H00300','raw','csi',1,'2000-02-29')")
            self.con.execute("INSERT INTO universe VALUES (0,'T01','{\"theme_id\":\"T01\"}')")
            self.con.execute("INSERT INTO meta VALUES ('historical-key','historical-value')")
            # 历史包的额外表、元数据亦不得被迁移重建或裁掉。
            self.con.execute("CREATE TABLE package(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
            self.con.execute("INSERT INTO package VALUES ('historical-package','keep')")

    def snapshot(self):
        tables = dict(TABLES, meta="key", package="key")
        return {name: [tuple(row) for row in self.con.execute(f"SELECT * FROM {name} ORDER BY {order}")]
                for name, order in tables.items()}

    def assert_unchanged(self, before, disk, schema):
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(DB.sha256_file(self.path), disk)
        self.assertEqual(schema_rows(self.con), schema)
        self.assertFalse(list(self.root.glob("*.sqlite-*")))

    def test_default_dryrun_and_readonly_connection_never_upgrade(self):
        before, disk, schema = self.snapshot(), DB.sha256_file(self.path), schema_rows(self.con)
        report = upgrade(self.path)
        self.assertEqual(report["operation"], "upgrade_date_constraints")
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["would_change"])
        self.assertFalse(report["applied"])
        self.assertFalse(report["changed"])
        self.assertEqual(report["invalid_dates"], [])
        self.assertEqual(report["invalid_count"], 0)
        self.assertIsNone(report["from_revision"])
        self.assertEqual(report["to_revision"], DATE_CONSTRAINT_VERSION)
        with contextlib.closing(DB.connect(self.path, readonly=True)) as readonly:
            self.assertEqual(readonly.execute("SELECT count(*) FROM bars").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                readonly.execute("DELETE FROM bars")
        with self.assertRaisesRegex(DB.DbError, "upgrade-date-constraints"):
            DB.connect(self.path)
        self.assert_unchanged(before, disk, schema)

    def test_apply_preserves_rows_original_ddl_pages_history_and_is_idempotent(self):
        before, old_schema = self.snapshot(), schema_rows(self.con)
        report = upgrade(self.path, apply=True)
        self.assertFalse(report["dry_run"])
        self.assertTrue(report["applied"])
        self.assertTrue(report["changed"])
        after = self.snapshot()
        self.assertEqual(after.pop("meta"), sorted(before["meta"] + [(DATE_CONSTRAINT_KEY, DATE_CONSTRAINT_VERSION)]))
        before.pop("meta")
        self.assertEqual(after, before)
        current = {row[1]: row for row in schema_rows(self.con)}
        for row in old_schema:
            self.assertEqual(current[row[1]], row)  # 原 DDL、root page、索引和触发器不动。
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        disk, schema, snapshot = DB.sha256_file(self.path), schema_rows(self.con), self.snapshot()
        for apply in (False, True, True):
            again = upgrade(self.path, apply=apply)
            self.assertTrue(again["idempotent"])
            self.assertFalse(again["changed"])
            self.assertFalse(again["would_change"])
            self.assert_unchanged(snapshot, disk, schema)
        with contextlib.closing(DB.connect(self.path)) as writable:
            self.assertEqual(writable.execute("SELECT max(run_id) FROM runs").fetchone()[0], 33)

    def test_invalid_existing_dates_abort_and_report_all_keys_without_normalizing(self):
        # 用合成注入模拟 SQLite 3.42 允许进入旧 CHECK 的日期，所有运行时都覆盖同一存量。
        self.con.execute("PRAGMA ignore_check_constraints=ON")
        with self.con:
            self.con.execute("INSERT INTO bars VALUES ('bad','raw','2026-02-30',NULL,NULL,NULL,1,NULL,NULL,'csi','keep')")
            self.con.execute("INSERT INTO calendar VALUES ('1900-02-29')")
            self.con.execute("UPDATE runs SET end_date='2100-02-29' WHERE run_id=1")
        self.con.execute("PRAGMA ignore_check_constraints=OFF")
        before, disk, schema = self.snapshot(), DB.sha256_file(self.path), schema_rows(self.con)
        for apply in (False, True):
            with self.assertRaises(UpgradeError) as caught:
                upgrade(self.path, apply=apply)
            report = caught.exception.report
            self.assertEqual(report["invalid_count"], 3)
            invalid = {row["table"]: row for row in report["invalid_dates"]}
            self.assertEqual(invalid["bars"]["column"], "date")
            self.assertEqual(invalid["bars"]["key"], {"code": "bad", "adj": "raw", "date": "2026-02-30"})
            self.assertEqual(invalid["calendar"]["key"], {"date": "1900-02-29"})
            self.assertEqual(invalid["runs"]["key"], {"run_id": 1})
            self.assertEqual(invalid["runs"]["column"], "end_date")
            self.assertEqual(invalid["runs"]["value"], "'2100-02-29'")
            self.assert_unchanged(before, disk, schema)

    def test_failed_revision_write_rolls_back_all_created_triggers_and_bytes(self):
        self.con.execute("CREATE TRIGGER block_revision BEFORE INSERT ON meta WHEN NEW.key='date_constraints' "
                         "BEGIN SELECT RAISE(ABORT, 'synthetic migration failure'); END")
        self.con.commit()
        before, disk, schema = self.snapshot(), DB.sha256_file(self.path), schema_rows(self.con)
        with self.assertRaisesRegex(DB.DbError, "synthetic migration failure"):
            upgrade(self.path, apply=True)
        self.assert_unchanged(before, disk, schema)

    def test_invalid_existing_nul_and_blob_are_reported_without_loss(self):
        values = ("2026-02-03\x00tail", b"2026-02-03")
        self.con.execute("PRAGMA ignore_check_constraints=ON")
        with self.con:
            for value in values:
                self.con.execute("INSERT INTO bars VALUES ('bad','raw',?,NULL,NULL,NULL,NULL,NULL,NULL,'csi','keep')", (value,))
        self.con.execute("PRAGMA ignore_check_constraints=OFF")
        before, disk, schema = self.snapshot(), DB.sha256_file(self.path), schema_rows(self.con)
        with self.assertRaises(UpgradeError) as caught:
            upgrade(self.path, apply=True)
        problems = caught.exception.report["invalid_dates"]
        self.assertEqual(caught.exception.report["invalid_count"], 2)
        self.assertEqual({row["value"] for row in problems}, {repr(value) for value in values})
        self.assertEqual({row["key"]["date"] for row in problems}, {values[0], repr(values[1])})
        json.dumps(caught.exception.report)  # CLI JSON 不能因为旧库 BLOB 而再次失败。
        self.assert_unchanged(before, disk, schema)

    def test_unknown_revision_and_conflicting_trigger_fail_without_mutation(self):
        trigger_name = next(iter(DATE_TRIGGERS))
        cases = (
            ("INSERT INTO meta VALUES (?, 'future-version')", (DATE_CONSTRAINT_KEY,)),
            (f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON bars BEGIN SELECT 1; END", ()),
        )
        for statement, args in cases:
            with self.subTest(statement=statement):
                with self.con:
                    self.con.execute(statement, args)
                before, disk, schema = self.snapshot(), DB.sha256_file(self.path), schema_rows(self.con)
                for apply in (False, True):
                    with self.assertRaises(DB.DbError):
                        upgrade(self.path, apply=apply)
                    self.assert_unchanged(before, disk, schema)
                with self.con:
                    self.con.execute("DELETE FROM meta WHERE key=?", (DATE_CONSTRAINT_KEY,))
                    self.con.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")

    def test_declared_revision_without_trigger_is_not_silently_repaired(self):
        upgrade(self.path, apply=True)
        self.con.execute(f"DROP TRIGGER {next(iter(DATE_TRIGGERS))}")
        self.con.commit()
        before, disk, schema = self.snapshot(), DB.sha256_file(self.path), schema_rows(self.con)
        with self.assertRaisesRegex(DB.DbError, "upgrade-date-constraints"):
            DB.connect(self.path)
        self.assert_unchanged(before, disk, schema)

    def test_cli_reports_invalid_dates_and_requires_apply_for_valid_upgrade(self):
        from src.data.__main__ import main
        args = ["upgrade-date-constraints", "--db", str(self.path)]
        disk = DB.sha256_file(self.path)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertEqual(DB.sha256_file(self.path), disk)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ["--apply"]), 0)
        self.assertTrue(json.loads(output.getvalue())["applied"])

    def test_cli_failure_reports_inventory_and_never_creates_missing_database(self):
        from src.data.__main__ import main
        self.con.execute("PRAGMA ignore_check_constraints=ON")
        with self.con:
            self.con.execute("UPDATE runs SET end_date='2026-02-30' WHERE run_id=1")
        disk = DB.sha256_file(self.path)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["upgrade-date-constraints", "--db", str(self.path), "--apply"]), 1)
        report = json.loads(error.getvalue())
        self.assertIn("error", report)
        self.assertEqual(report["invalid_count"], 1)
        self.assertEqual(report["invalid_dates"][0]["key"], {"run_id": 1})
        self.assertEqual(DB.sha256_file(self.path), disk)
        missing = self.root / "missing.sqlite"
        for apply in (False, True):
            with self.assertRaises(DB.DbError):
                upgrade(missing, apply=apply)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
