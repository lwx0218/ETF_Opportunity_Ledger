"""Synthetic qualification, cutoff and preservation regressions; no formal data."""
from __future__ import annotations

import json
import math
import sqlite3
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.data import db as DB
from src.observation import observe
from src.observation.metrics import choose_volume, frame, native_frame
from src.indicators.states import form_states

NOW = datetime(2026, 10, 6, 18, tzinfo=ZoneInfo("Asia/Shanghai"))


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(DB.SCHEMA)
        self.days = pd.bdate_range("2022-01-03", periods=650)
        self.con.executemany("INSERT INTO calendar VALUES (?)", [(str(d.date()),) for d in self.days])
        self.con.execute("INSERT INTO runs(kind,started_at,status) VALUES ('backfill','2026-01-01','ok')")
        self.add_container("T01", "ONE", 0)
        self.seed("H00300", "csi")
        self.seed("ONE", "csi")

    def tearDown(self):
        self.con.close()

    def add_container(self, tid, code, order, *, source="csi", first=None, price=None, execution=None):
        item = {"theme_id": tid, "theme": "容器" + tid, "status": "retained", "line": "宽基",
                "research_index_code": price or code, "execution_fund_code": execution or "ETF" + tid}
        self.con.execute("INSERT INTO universe VALUES (?,?,?)", (order, tid, json.dumps(item)))
        self.con.execute("INSERT INTO coverage(run_id,theme_id,container,status,series_code,series_adj,route_used,code,price_only,first_date,exec_code,exec_route) "
                         "VALUES (1,?,?,?,?,?,?,?,?,?,?,?)", (tid, item["theme"], "retained", code, "raw", source,
                         price or code, "false", first or str(self.days[0].date()), execution or "ETF" + tid, "tencent_etf"))

    def seed(self, code, source, *, days=None, volume=100, close_only=False):
        chosen = self.days[:600] if days is None else days
        data = []
        for i, d in enumerate(chosen):
            close = 100 + i * 0.1 + math.sin(i / 7)
            data.append((code, "raw", str(d.date()), None if close_only else close - .1,
                         None if close_only else close + 1, None if close_only else close - 1,
                         close, volume, None, source, "2026-10-01T03:00:00Z"))
        self.con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", data)

    def replace(self, code, day, **updates):
        old = dict(self.con.execute("SELECT * FROM bars WHERE code=? AND date=?", (code, str(day.date()))).fetchone())
        old.update(updates)
        self.con.execute("DELETE FROM bars WHERE code=? AND date=?", (code, str(day.date())))
        self.con.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(old.values()))

    def observe(self, index=599, **kwargs):
        return observe(self.con, self.days[index].date(), now=NOW, weeks=2, **kwargs)

    def field(self, report, field, index=0):
        return report["containers"][index]["fields"][field]

    def snapshot(self):
        schema = tuple(tuple(r) for r in self.con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        tables = [r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        contents = []
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            contents.append((table, tuple(sorted((tuple(r) for r in self.con.execute(f"SELECT * FROM {quoted}")), key=repr))))
        return schema, tuple(contents)

    def test_reads_only_and_preserves_all_rows_with_full_field_identity(self):
        before = self.snapshot()
        writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE,
                  sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}
        self.con.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK)
        result = self.observe()
        self.con.set_authorizer(None)
        self.assertEqual(before, self.snapshot())
        json.dumps(result, allow_nan=False)
        field = self.field(result, "rs_1m")
        self.assertEqual(field["value"], 0)
        for key in ("code", "adj", "source", "purpose", "price_basis", "observation_date", "native_date", "window", "fetched_at"):
            self.assertIn(key, field)
        self.assertEqual(field["source"], "csi")
        self.assertEqual(field["price_basis"], "全收益指数")

    def test_clock_uses_shanghai_fifteen_and_calendar_not_last_bar(self):
        monday = next(d for d in self.days[50:] if d.weekday() == 0)
        before = datetime.combine(monday.date(), datetime.min.time()).replace(hour=14, minute=59, tzinfo=ZoneInfo("Asia/Shanghai"))
        after = before.replace(hour=15, minute=0)
        a = observe(self.con, now=before, weeks=1)
        b = observe(self.con, now=after, weeks=1)
        self.assertEqual(a["effective_date"], str((monday - pd.Timedelta(days=3)).date()))
        self.assertEqual(b["effective_date"], str(monday.date()))
        self.assertIsNone(observe(self.con, monday.date(), now=before)["effective_date"])
        weekend = monday - pd.Timedelta(days=1)
        self.assertEqual(observe(self.con, weekend.date(), now=after, weeks=1)["effective_date"], a["effective_date"])
        stale = self.observe(610)
        self.assertEqual(stale["effective_date"], str(self.days[610].date()))
        self.assertEqual(stale["actual_data_end"], str(self.days[599].date()))
        self.assertIsNone(self.field(stale, "close")["value"])
        self.assertIsNone(observe(self.con, date(2021, 1, 1), now=NOW)["effective_date"])
        self.assertIsNone(observe(self.con, now=NOW)["effective_date"])

    def test_selected_research_does_not_fall_back_to_execution_or_candidate(self):
        self.con.execute("DELETE FROM bars WHERE code='ONE'")
        self.seed("ETFT01", "tencent_etf")
        self.seed("PRICE", "tencent_price_index_offline")
        self.con.execute("UPDATE coverage SET code='PRICE'")
        result = self.observe(series_kind="execution")
        json.dumps(result, allow_nan=False)
        self.assertIsNone(self.field(result, "close")["value"])
        self.assertEqual(result["containers"][0]["identity"]["code"], "ONE")
        self.assertGreater(result["detail"]["chart"][-1]["close"], 0)
        self.assertFalse(result["detail"]["fields"]["rs_1m"]["available"])
        candidate = self.observe(series_kind="price_candidate")["detail"]
        self.assertTrue(candidate["identity"]["price_only"])
        self.assertEqual(candidate["identity"]["source"], "tencent_price_index_offline")
        self.assertEqual(candidate["identity"]["price_basis"], "价格指数（不含分红再投）")
        self.assertTrue(all(r["volume"] is None for r in candidate["chart"]))

    def test_missing_declared_prefix_cannot_restart_state_warmup(self):
        self.con.execute("DELETE FROM bars WHERE code='ONE' AND date<?", (str(self.days[30].date()),))
        result = self.observe(149)
        self.assertFalse(self.field(result, "state")["available"])
        self.assertFalse(self.field(result, "ext")["available"])
        self.assertEqual(self.field(result, "state")["window"]["start"], str(self.days[0].date()))
        self.assertTrue(self.field(result, "rs_1m")["available"])
        self.assertTrue(self.field(result, "atr20")["available"])

    def test_overseas_missing_declared_native_prefix_does_not_restart_ema(self):
        self.add_container("T02", "FOREIGN", 1, source="yahoo")
        self.seed("FOREIGN", "yahoo", days=self.days[:160])
        self.con.execute("DELETE FROM bars WHERE code='FOREIGN' AND date<?", (str(self.days[30].date()),))
        result = self.observe(149)
        self.assertFalse(self.field(result, "state", 1)["available"])
        self.assertIn("前缀", self.field(result, "state", 1)["reason"])
        self.assertTrue(self.field(result, "rs_1m", 1)["available"])
        self.assertTrue(self.field(result, "atr20", 1)["available"])

    def test_close_only_is_visible_but_never_fabricates_candles_atr_or_state(self):
        self.con.execute("DELETE FROM bars WHERE code='ONE'")
        self.seed("ONE", "csi", close_only=True)
        result = self.observe()
        self.assertTrue(self.field(result, "close")["available"])
        self.assertTrue(self.field(result, "rs_1m")["available"])
        self.assertFalse(self.field(result, "atr20")["available"])
        self.assertFalse(self.field(result, "state")["available"])
        self.assertTrue(result["benchmark_ready"])
        self.assertFalse(result["research_ready"])
        row = result["detail"]["chart"][-1]
        self.assertGreater(row["close"], 0)
        self.assertIsNone(row["open"])
        self.assertIsNone(row["high"])
        self.assertIsNone(row["low"])

    def test_interior_missing_close_blocks_rs_without_compressing_window(self):
        self.con.execute("DELETE FROM bars WHERE code='ONE' AND date=?", (str(self.days[590].date()),))
        result = self.observe()
        self.assertFalse(self.field(result, "rs_1m")["available"])
        self.assertEqual(self.field(result, "rs_1m")["window"]["points"], 21)
        self.assertFalse(result["comparison"]["comparison_complete"])
        self.assertIsNone(self.field(result, "rank")["value"])
        gap = next(r for r in result["detail"]["chart"] if r["date"] == str(self.days[590].date()))
        self.assertIsNone(gap["close"])
        self.assertIn("缺", gap["close_reason"])

    def test_missing_benchmark_interior_does_not_fall_back_to_absolute_return(self):
        self.con.execute("DELETE FROM bars WHERE code='H00300' AND date=?", (str(self.days[590].date()),))
        result = self.observe()
        self.assertIn("基准", self.field(result, "rs_1m")["reason"])
        self.assertFalse(result["benchmark_ready"])

    def test_old_ohl_anomaly_keeps_chart_gap_but_qualified_state_uses_full_ema(self):
        self.replace("ONE", self.days[200], high=0.1)
        result = self.observe(chart_points=500)
        self.assertTrue(self.field(result, "atr20")["available"])
        self.assertTrue(self.field(result, "state")["available"])
        bad = next(r for r in result["detail"]["chart"] if r["date"] == str(self.days[200].date()))
        self.assertIsNone(bad["high"])
        self.assertIn("包络", bad["ohlc_reason"])
        smaller = self.observe(chart_points=30)
        self.assertEqual(self.field(result, "state"), self.field(smaller, "state"))
        native = frame([dict(r) for r in self.con.execute("SELECT * FROM bars WHERE code='ONE' ORDER BY date")])
        exact = form_states(native).iloc[-1]
        self.assertEqual(self.field(result, "state")["value"], exact["state"])
        self.assertEqual(self.field(result, "ext")["value"], exact["ext"])
        self.replace("ONE", self.days[599], low=999)
        self.assertFalse(self.field(self.observe(), "atr20")["available"])
        self.assertFalse(self.field(self.observe(), "state")["available"])

    def test_old_close_gap_still_blocks_ema_even_with_recent_good_rows(self):
        self.replace("ONE", self.days[200], close=None)
        result = self.observe()
        self.assertFalse(self.field(result, "state")["available"])
        self.assertIn("EMA", self.field(result, "state")["reason"])
        self.assertTrue(self.field(result, "rs_1m")["available"])

    def test_seventy_native_rows_state_warmup_and_atr14_extension(self):
        early, ready = self.observe(68), self.observe(69)
        self.assertFalse(self.field(early, "state")["available"])
        self.assertTrue(self.field(ready, "state")["available"])
        self.assertEqual(self.field(ready, "ext")["denominator"], "ATR14")
        self.assertEqual(self.field(ready, "atr20")["window"]["required"], 20)
        self.assertEqual(self.field(ready, "state")["window"]["required"], 70)

    def test_rank_ties_keep_universe_order_and_unknown_pool_gap_hides_all_ranks(self):
        self.add_container("T02", "TWO", 1)
        self.seed("TWO", "csi")
        report = self.observe()
        self.assertEqual([r["theme_id"] for r in report["containers"]], ["T01", "T02"])
        self.assertEqual([r["fields"]["rank"]["value"] for r in report["containers"]], [1, 1])
        self.con.execute("DELETE FROM bars WHERE code='TWO' AND date=?", (str(self.days[590].date()),))
        report = self.observe()
        self.assertFalse(report["comparison"]["comparison_complete"])
        self.assertEqual(report["comparison"]["pool"], 2)
        self.assertEqual(report["comparison"]["valid"], 1)
        self.assertTrue(all(r["fields"]["rank"]["value"] is None for r in report["containers"]))

    def test_declared_listing_and_warmup_are_explicit_exclusions(self):
        self.add_container("T02", "TWO", 1, first=str(self.days[590].date()))
        self.seed("TWO", "csi", days=self.days[590:600])
        early = self.observe(580)
        recent = self.observe()
        for report in (early, recent):
            self.assertEqual(report["comparison"]["pool"], 2)
            self.assertEqual(report["comparison"]["valid"], 1)
            self.assertTrue(report["comparison"]["comparison_complete"])
            self.assertEqual(report["comparison"]["excluded"][0]["theme_id"], "T02")

    def test_overseas_warmup_counts_aligned_points_not_native_bars(self):
        self.add_container("T02", "FOREIGN", 1, source="yahoo", first=str(self.days[40].date()))
        self.seed("FOREIGN", "yahoo", days=self.days[40:63])
        self.con.executemany("DELETE FROM calendar WHERE date=?", [(str(d.date()),) for d in self.days[45:50]])
        result = self.observe(63)
        self.assertIsNone(self.field(result, "rs_1m", 1)["value"])
        self.assertEqual(self.field(result, "rs_1m", 1)["window"]["points"], 18)
        self.assertTrue(result["comparison"]["comparison_complete"])
        self.assertEqual(result["comparison"]["excluded"][0]["theme_id"], "T02")

    def test_volume_choice_cutoff_precedes_ratio_and_tencent_candidate_never_borrowed(self):
        native = frame([{"date": str(d.date()), "close": 10, "open": 10, "high": 11, "low": 9,
                         "volume": 10 if i < 30 else None, "source": "csi"} for i, d in enumerate(self.days[:100])])
        price = native.assign(volume=100, source="csi")
        ident = {"code": "TR", "source": "csi"}
        old = native_frame(native, ident, self.days, self.days[29])
        self.assertEqual(choose_volume(old, price, ident, "PRICE", self.days[29])[1], "self")
        later = native_frame(native, ident, self.days, self.days[99])
        self.assertEqual(choose_volume(later, price, ident, "PRICE", self.days[99])[1], "price_version")
        self.assertEqual(choose_volume(later, price.assign(source="tencent_price_index_offline"), ident, "PRICE", self.days[99])[1], "none")

    def test_invalid_self_and_none_volume_never_satisfies_surge_conditions(self):
        native = frame([{"date": str(d.date()), "close": 200 - i if i < 99 else 220,
                         "open": 200 - i if i < 99 else 220,
                         "high": 201 - i if i < 99 else 221, "low": 199 - i if i < 99 else 219,
                         "volume": -1, "source": "csi"} for i, d in enumerate(self.days[:100])])
        # The unqualified source values reproduce the defect in the unchanged
        # formal algorithm: -1 > 1.5 * -1 incorrectly counts as a volume surge.
        self.assertEqual(form_states(native).iloc[-1]["state"], "POP")
        ident = {"code": "ONE", "source": "csi"}
        for own_rows, expected in ((0, "none"), (5, "none"), (80, "self")):
            for invalid in (-1, 0, float("inf"), float("-inf"), None):
                with self.subTest(own_rows=own_rows, invalid=invalid):
                    raw = native.assign(volume=invalid)
                    raw.loc[:own_rows - 1, "volume"] = 100
                    raw = frame(raw.to_dict("records"))
                    before = raw.copy(deep=True)
                    computed, source = choose_volume(raw, frame([]), ident, "ONE", self.days[99])
                    self.assertEqual(source, expected)
                    pd.testing.assert_frame_equal(raw, before)
                    self.assertTrue(computed["volume"].iloc[own_rows:].isna().all())
                    self.assertEqual(int(computed["volume"].notna().sum()), own_rows)
                    self.assertNotIn(form_states(computed).iloc[-1]["state"], ("POP", "REV", "EXH", "DROP"))

    def test_observation_negative_volume_is_limited_without_rewriting_source(self):
        for i, day in enumerate(self.days[:100]):
            close = 200 - i if i < 99 else 220
            self.replace("ONE", day, open=close, high=close + 1, low=close - 1, close=close, volume=-1)
        before = self.snapshot()
        result = self.observe(99)
        state = self.field(result, "state")
        self.assertEqual(state["value"], "NEUTRAL")
        self.assertEqual(state["qualification"], "volume_limited")
        self.assertEqual(state["volume_source"], "none")
        self.assertEqual(before, self.snapshot())
        self.assertTrue(all(r["volume"] is None for r in result["detail"]["chart"]))

    def test_future_rows_do_not_change_historical_columns_including_volume_source(self):
        self.con.execute("UPDATE coverage SET code='PRICE'")
        self.seed("PRICE", "csi", volume=200)
        before = self.observe(150)
        self.con.execute("DELETE FROM bars WHERE date>?", (str(self.days[150].date()),))
        after = self.observe(150)
        self.assertEqual(before["containers"], after["containers"])
        self.assertEqual(before["rotation"], after["rotation"])
        self.assertEqual(before["detail"]["fields"], after["detail"]["fields"])

    def test_overseas_d_minus_one_and_fifth_stale_day_boundary(self):
        self.add_container("T02", "FOREIGN", 1, source="yahoo")
        self.seed("FOREIGN", "yahoo", days=self.days[:100])
        first = self.observe(99)
        self.assertEqual(first["containers"][1]["native_date"], str(self.days[98].date()))
        fourth = self.observe(104)
        fifth = self.observe(105)
        self.assertEqual(fourth["containers"][1]["data_hole"], 0)
        self.assertEqual(fifth["containers"][1]["data_hole"], 1)
        self.assertFalse(self.field(fifth, "state", 1)["available"])
        self.assertFalse(self.field(fifth, "rank", 1)["available"])
        self.assertEqual(fifth["containers"][1]["native_date"], str(self.days[99].date()))
        self.assertIn("data_hole", self.field(fifth, "state", 1)["reason"])

    def test_month_end_value_has_real_month_and_missing_month_never_compresses(self):
        result = self.observe()
        z = self.field(result, "z_month")
        self.assertTrue(z["available"])
        self.assertEqual(z["window"]["required"], 21)
        ends = self.days.to_series().groupby(self.days.to_period("M")).last()
        prior = ends[ends < self.days[599]].iloc[-4]
        self.con.execute("DELETE FROM bars WHERE code='ONE' AND date=?", (str(prior.date()),))
        broken = self.field(self.observe(), "z_month")
        self.assertIsNone(broken["value"])
        self.assertIn("缺月不压缩", broken["reason"])
        self.assertLess(z["value_date"], str(self.days[599].date()))

    def test_week_columns_share_official_day_and_incomplete_week_is_labelled(self):
        self.add_container("T02", "TWO", 1)
        self.seed("TWO", "csi")
        wednesday = next(i for i in range(570, 599) if self.days[i].weekday() == 2)
        result = self.observe(wednesday)
        self.assertTrue(result["weeks"][-1]["partial"])
        for row in result["rotation"]:
            self.assertEqual([c["date"] for c in row["cells"]], [w["date"] for w in result["weeks"]])
            self.assertEqual(row["cells"][-1]["state"]["observation_date"], result["effective_date"])
        self.assertTrue(all(point["volume"] is None for point in result["detail"]["chart"]))
        self.assertEqual(result["detail"]["volume"]["unit"], "unverified")

    def test_friday_official_holiday_finishes_week_on_thursday(self):
        thursday = next(i for i in range(570, 599) if self.days[i].weekday() == 3)
        self.con.execute("DELETE FROM calendar WHERE date=?", (str(self.days[thursday + 1].date()),))
        result = self.observe(thursday)
        self.assertFalse(result["weeks"][-1]["partial"])
        self.assertEqual(result["weeks"][-1]["date"], str(self.days[thursday].date()))

    def test_zero_monthly_standard_deviation_is_unavailable(self):
        ends = self.days[:600].to_series().groupby(self.days[:600].to_period("M")).last()
        for day in ends:
            self.replace("ONE", day, open=100, high=101, low=99, close=100)
        z = self.field(self.observe(), "z_month")
        self.assertIsNone(z["value"])
        self.assertIn("标准差为零", z["reason"])


if __name__ == "__main__":
    unittest.main()
