"""卡片存储：锁死字段、§2.5 每条禁令、作废重建、分母。只用内存数据库与仓库里的固定源清单。

运行：python -m unittest discover -s tests -t .
"""
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ledger.store import CARD_FIELDS, Ledger, LedgerError, mechanical_score   # noqa: E402

A_SRC, B_SRC, C_SRC = "ENE-EIA-WPSR", "GEO-UKMTO-WARN", "ENE-OPEC-MOMR"


def card(**over):
    c = dict(created_at="2026-10-09T16:05", close_date="2026-10-09", container="半导体", instrument_code="512480",
             instrument_name="国联安中证全指半导体ETF", research_index_code="H30184", trigger_type="形态突破",
             state_at_entry="BNB", thesis="平台突破且近一月相对强弱前 20%", expectation_horizon_days=20,
             expectation_target_excess_pct=5.0, expectation_benchmark="等权组合", invalidation_price=9.2,
             invalidation_atr_value=0.4, invalidation_atr_multiple=2.0, r_unit_per_share=0.8, r_unit_pct_of_nav=0.5,
             planned_size_pct=6.25, cf_ew_level=1.0, cf_hs300_level=5000.0, cf_container_price=10.0,
             crowd_rs_1m_rank=2, crowd_premium_pct=None, owner_score_deadline="2026-10-10T09:30")
    c.update(over)
    return c


def ev(**over):
    e = dict(source_id=A_SRC, published_at="2026-10-08T22:30", summary="EIA 商业原油库存降幅大于预期",
             url="https://www.eia.gov/petroleum/supply/weekly/", first_seen_at="2026-10-08T22:40",
             available_at="2026-10-08T22:30", snapshot_path="snapshots/2026-10-08/psw00.pdf", snapshot_sha256="a" * 64)
    e.update(over)
    return e


AGENT = dict(score=3, reason="一手数据，方向与论点一致", scored_at="2026-10-09T16:05")


class Base(unittest.TestCase):
    def setUp(self):
        self.L = Ledger(":memory:")
        self.addCleanup(self.L.close)

    def make(self, evidence=None, **over):
        c = card(**over)
        return self.L.create_card(c, [ev()] if evidence is None else evidence, dict(AGENT, scored_at=c["created_at"]))

    def raw(self, sql, *args):
        self.L.conn.execute(sql, args)

    def rejects(self, sql, *args, msg=""):
        with self.assertRaisesRegex(sqlite3.DatabaseError, msg):
            self.raw(sql, *args)


class Creation(Base):
    def test_create_and_read_back(self):
        cid = self.make()
        self.assertEqual(cid, "T-2026-001")
        self.assertEqual(self.L.status(cid), "候选")
        self.assertEqual(self.L.card(cid)["scoring_rule"], "schema-v1-§3")
        self.assertEqual(self.L.card(cid)["tracking_days"], 20)
        self.assertEqual(len(self.L.evidence(cid)), 1)
        self.assertEqual(self.make(), "T-2026-002")

    def test_empty_evidence_is_legal(self):
        cid = self.make(evidence=[])
        self.assertEqual(self.L.evidence(cid), [])

    def test_rejected_evidence_rolls_back_whole_card(self):
        for bad, msg in [(dict(source_id="NOT-IN-LIST"), "固定源"), (dict(source_id=C_SRC), "A 或 B"),
                         (dict(available_at="2026-10-09T16:06", first_seen_at="2026-10-09T16:00"), "available_at"),
                         (dict(first_seen_at="2026-10-09T16:10"), "first_seen_at"),
                         (dict(available_at="2026-10-07T00:00"), "CHECK"),                 # 早于发布
                         (dict(snapshot_sha256="xyz"), "CHECK")]:
            with self.subTest(msg), self.assertRaisesRegex(LedgerError, msg):
                self.make(evidence=[ev(**bad)])
        self.assertEqual(self.L.conn.execute("SELECT count(*) FROM cards").fetchone()[0], 0)

    def test_b_grade_source_is_accepted(self):
        self.make(evidence=[ev(source_id=B_SRC, published_at="2026-10-08", available_at="2026-10-09T00:00")])

    def test_field_checks(self):
        cases = [(dict(thesis="长" * 81), "CHECK"), (dict(created_at="2026-10-09T14:59"), "CHECK"),
                 (dict(scoring_rule="自由填写"), "CHECK"), (dict(expectation_benchmark="标的自身"), "CHECK"),
                 (dict(trigger_type="事件驱动"), "CHECK"),                         # A3：事件卡缺论点失效条件
                 (dict(trigger_type="事件驱动", thesis_inval_source_id=C_SRC, thesis_inval_deadline="2026-11-01",
                       thesis_inval_statement="11 月 1 日前 OPEC 宣布增产即失效"), "A / B"),
                 (dict(owner_score_deadline="2026-10-09T16:00"), "CHECK"), (dict(state_at_entry="启动"), "CHECK"),
                 (dict(planned_size_pct=30), "CHECK")]
        for over, msg in cases:
            with self.subTest(over), self.assertRaisesRegex(LedgerError, msg):
                self.make(**over)

    def test_event_card(self):
        cid = self.make(trigger_type="事件驱动", thesis_inval_source_id=A_SRC, thesis_inval_deadline="2026-10-22",
                        thesis_inval_statement="10 月 22 日前 EIA 周报显示库存转为增加即失效")
        self.assertEqual(self.L.card(cid)["thesis_inval_source_id"], A_SRC)

    def test_seal_requires_agent_score(self):
        c = card(id="T-2026-900", scoring_rule="schema-v1-§3")
        self.raw(f"INSERT INTO cards ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", *c.values())
        self.rejects("UPDATE cards SET sealed = 1 WHERE id = 'T-2026-900'")

    def test_cannot_insert_sealed_card_directly(self):
        c = card(id="T-2026-901", scoring_rule="schema-v1-§3", sealed=1)
        self.rejects(f"INSERT INTO cards ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", *c.values())


class Section25(Base):
    """schema §2.5 明令禁止——每条一个失败测试。"""

    def test_no_evidence_added_after_creation(self):
        cid = self.make()
        with self.assertRaisesRegex(LedgerError, "事后添加"):
            self.L._tx(lambda: self.L._insert("evidence", {"card_id": cid, "seq": 2, **ev()}))

    def test_no_evidence_modified(self):
        cid = self.make()
        self.rejects("UPDATE evidence SET summary = '改过' WHERE card_id = ?", cid)
        self.rejects("UPDATE evidence SET source_id = ? WHERE card_id = ?", B_SRC, cid)

    def test_frozen_fields_cannot_change(self):
        cid = self.make()
        types = {r[1]: r[2] for r in self.L.conn.execute("PRAGMA table_info(cards)")}
        for col in CARD_FIELDS:                         # 含 expectation / invalidation / scoring_rule 全部列
            change = f"coalesce({col}, '') || 'x'" if types[col] == "TEXT" else f"coalesce({col}, 0) + 1"
            with self.subTest(col):
                self.rejects(f"UPDATE cards SET {col} = {change} WHERE id = ?", cid, msg="锁死")     # 触发器拒绝，不是 CHECK
        self.rejects("UPDATE cards SET sealed = 0 WHERE id = ?", cid, msg="锁死")
        self.assertEqual(self.L.card(cid)["expectation_target_excess_pct"], 5.0)

    def test_evidence_strength_locked(self):
        cid = self.make()
        self.rejects("UPDATE strength_scores SET score = 5 WHERE card_id = ?", cid)
        self.rejects("INSERT INTO strength_scores VALUES (?, 'agent', 5, '再打一次', '2026-10-09T17:00')", cid)
        self.L.owner_score(cid, 2, "只有一条库存数据", "2026-10-10T08:00")
        with self.assertRaises(LedgerError):
            self.L.owner_score(cid, 4, "改主意", "2026-10-10T09:00")
        self.rejects("UPDATE strength_scores SET score = 5 WHERE card_id = ? AND rater = 'owner'", cid)

    def test_owner_score_after_deadline_is_missing(self):
        cid = self.make()
        with self.assertRaisesRegex(LedgerError, "截止"):
            self.L.owner_score(cid, 2, "晚了", "2026-10-10T09:31")
        self.assertIsNone(self.L.conn.execute("SELECT owner_strength FROM card_status WHERE id = ?", (cid,)).fetchone()[0])

    def test_no_card_deleted_including_voided(self):
        a, b = self.make(), self.make()
        self.L.void(b, "未进场而失效", "2026-10-12T16:00")
        for cid in (a, b):
            self.rejects("DELETE FROM cards WHERE id = ?", cid)
        for t in ("evidence", "strength_scores", "voids"):
            self.rejects(f"DELETE FROM {t}")
        self.assertEqual(self.L.summary()["denominator"], 2)

    def test_correction_only_by_void_and_supersede(self):
        old = self.make()
        with self.assertRaisesRegex(LedgerError, "supersedes"):
            self.make(supersedes=old)                                       # 旧卡未作废
        self.L.void(old, "论点写错，重建", "2026-10-09T16:30")
        with self.assertRaisesRegex(LedgerError, "supersedes"):
            self.make(supersedes=old, created_at="2026-10-09T16:20")         # 新卡早于作废时刻
        new = self.make(supersedes=old, created_at="2026-10-09T16:31", owner_score_deadline="2026-10-10T09:30",
                        thesis="修正后的论点", invalidation_price=9.0)
        with self.assertRaises(LedgerError):
            self.make(supersedes=old, created_at="2026-10-09T16:40")         # 一张旧卡只能被取代一次
        s = self.L.summary()
        self.assertEqual((s["denominator"], s["by_status"], s["superseded"]), (2, {"作废": 1, "候选": 1}, 1))
        self.assertEqual(self.L.card(new)["supersedes"], old)


class Lifecycle(Base):
    def run_to_exit(self, reason="移动止盈", r=1.8, excess=6.0, manual=None):
        cid = self.make()
        self.L.enter(cid, "2026-10-12", 10.05, 6.25)
        self.L.append_daily(cid, dict(date="2026-10-12", close=10.2, state="TREND_UP", r_current=0.19, mfe=0.2, mae=-0.1, stop_now=9.2))
        self.L.append_daily(cid, dict(date="2026-10-13", close=10.6, state="TREND_UP", r_current=0.69, mfe=0.7, mae=-0.1, stop_now=9.2))
        self.L.exit(cid, exit_date="2026-11-20", exit_price=11.5, exit_reason=reason, manual_reason=manual,
                    realized_r=r, realized_excess_pct=excess, holding_days=28)
        return cid

    def test_full_path_and_mechanical_score(self):
        cid = self.run_to_exit()
        self.assertEqual(self.L.status(cid), "过去")
        with self.assertRaisesRegex(LedgerError, "机械"):
            self.L.finalize(cid, post_exit_return_pct=2.0, post_exit_r=0.5, final_score="部分", missed_r=0.3,
                            stop_quality=0, trail_quality=1, benchmark_beat=1)
        self.L.finalize(cid, post_exit_return_pct=2.0, post_exit_r=0.5, final_score="达标", missed_r=0.3,
                        stop_quality=0, trail_quality=1, benchmark_beat=1)
        self.assertEqual(self.L.status(cid), "已结")
        for t in ("entries", "daily", "exits", "finals"):
            self.rejects(f"UPDATE {t} SET recorded_at = 'x' WHERE card_id = ?" if t != "daily" else
                         "UPDATE daily SET close = 1 WHERE card_id = ?", cid)
            self.rejects(f"DELETE FROM {t} WHERE card_id = ?", cid)
        with self.assertRaisesRegex(LedgerError, "已跟踪期满"):
            self.L.append_daily(cid, dict(date="2026-12-01", close=12, state="NEUTRAL"))

    def test_mechanical_score_rules(self):
        self.assertEqual(mechanical_score("失效位", 10.0, 5.0), "证伪")
        self.assertEqual(mechanical_score("移动止盈", 5.0, 5.0), "达标")
        self.assertEqual(mechanical_score("跟踪期满", 0.1, 5.0), "部分")
        self.assertEqual(mechanical_score("手动", 0.0, 5.0), "未达")

    def test_stop_exit_scores_falsified(self):
        cid = self.run_to_exit(reason="失效位", r=-1.05, excess=-4.0)
        self.L.finalize(cid, post_exit_return_pct=8.0, post_exit_r=1.2, final_score="证伪", missed_r=1.2,
                        stop_quality=1, trail_quality=None, benchmark_beat=0)

    def test_manual_exit_needs_reason(self):
        with self.assertRaises(LedgerError):
            self.run_to_exit(reason="手动")
        cid = self.run_to_exit(reason="手动", manual="临停，流动性不足")
        self.assertEqual(self.L.summary()["manual_exit_share"], 1.0)
        self.assertEqual(self.L.status(cid), "过去")

    def test_order_rules(self):
        cid = self.make()
        with self.assertRaisesRegex(LedgerError, "没有进场"):
            self.L.exit(cid, exit_date="2026-10-12", exit_price=10, exit_reason="失效位", realized_r=-1, realized_excess_pct=-3, holding_days=0)
        with self.assertRaisesRegex(LedgerError, "晚于信号收盘日"):
            self.L.enter(cid, "2026-10-09", 10.0, 5)
        self.L.enter(cid, "2026-10-12", 10.0, 5)
        with self.assertRaises(LedgerError):
            self.L.enter(cid, "2026-10-13", 10.0, 5)                       # 只能进场一次
        self.L.append_daily(cid, dict(date="2026-10-13", close=10.1, state="XB"))
        with self.assertRaisesRegex(LedgerError, "向后追加"):
            self.L.append_daily(cid, dict(date="2026-10-12", close=10.0, state="XB"))

    def test_void_rules(self):
        cand = self.make()
        self.L.void(cand, "未进场而失效：次日跳空低于失效位", "2026-10-12T09:31")
        self.assertEqual(self.L.status(cand), "作废")
        with self.assertRaisesRegex(LedgerError, "作废"):
            self.L.enter(cand, "2026-10-12", 10.0, 5)
        with self.assertRaises(LedgerError):
            self.L.void(cand, "再作废一次", "2026-10-12T10:00")
        done = self.run_to_exit()
        with self.assertRaisesRegex(LedgerError, "已出场"):
            self.L.void(done, "事后不想要了", "2026-11-21T10:00")


class Statistics(Base):
    def test_voided_and_unentered_cards_count_in_denominator(self):
        ids = [self.make() for _ in range(4)]
        self.L.void(ids[0], "未进场而失效", "2026-10-12T16:00")
        self.L.enter(ids[1], "2026-10-12", 10.0, 5)
        self.L.exit(ids[1], exit_date="2026-11-10", exit_price=11, exit_reason="移动止盈", realized_r=1.2, realized_excess_pct=6.0, holding_days=20)
        self.L.finalize(ids[1], post_exit_return_pct=0, post_exit_r=0, final_score="达标", missed_r=0, stop_quality=0, trail_quality=1, benchmark_beat=1)
        s = self.L.summary()
        self.assertEqual(s["denominator"], 4)
        self.assertEqual(s["hit_rate_over_all_cards"], 0.25)                # 1 张达标 / 4 张（含作废、候选）
        cal = self.L.calibration("agent")
        self.assertEqual([(c["bucket"], c["n"], c["voided"], c["hits"]) for c in cal], [("2–3", 4, 1, 1)])
        self.assertFalse(cal[0]["enough"])
        self.assertEqual(self.L.calibration("owner"), [])                     # owner 全部缺失


class SchemaCoverage(unittest.TestCase):
    """docs/etf-card-schema-v1.md §2 的每个字段都有落点（表, 列）。"""
    FIELDS = {
        "id": [("cards", "id")], "created_at": [("cards", "created_at"), ("cards", "close_date")], "container": [("cards", "container")],
        "instrument": [("cards", "instrument_code"), ("cards", "instrument_name"), ("cards", "research_index_code")],
        "trigger_type": [("cards", "trigger_type")], "state_at_entry": [("cards", "state_at_entry")], "thesis": [("cards", "thesis")],
        "evidence[]": [("evidence", c) for c in ("source_id", "published_at", "summary", "url", "first_seen_at", "available_at",
                                                 "snapshot_path", "snapshot_sha256")],
        "evidence_strength": [("strength_scores", "score"), ("strength_scores", "reason"), ("strength_scores", "rater")],
        "expectation": [("cards", "expectation_horizon_days"), ("cards", "expectation_target_excess_pct"), ("cards", "expectation_benchmark")],
        "invalidation": [("cards", "invalidation_price"), ("cards", "invalidation_atr_value"), ("cards", "invalidation_atr_multiple")],
        "r_unit": [("cards", "r_unit_per_share"), ("cards", "r_unit_pct_of_nav")], "planned_size_pct": [("cards", "planned_size_pct")],
        "scoring_rule": [("cards", "scoring_rule")], "tracking_days": [("cards", "tracking_days")],
        "counterfactual": [("cards", "cf_ew_level"), ("cards", "cf_hs300_level"), ("cards", "cf_container_price")],
        "crowding_at_entry": [("cards", c) for c in ("crowd_rs_1m_rank", "crowd_rs_3m_rank", "crowd_vol_ratio_20", "crowd_premium_pct", "crowd_share_chg_20d")],
        "supersedes": [("cards", "supersedes")],
        **{f: [("daily", f)] for f in ("date", "close", "state", "z", "rs_1m_rank", "r_current", "mfe", "mae", "stop_now", "bench_close", "note")},
        **{f: [("exits", f)] for f in ("exit_date", "exit_price", "exit_reason", "realized_r", "realized_excess_pct", "holding_days")},
        **{f: [("finals", f)] for f in ("post_exit_return_pct", "post_exit_r", "final_score", "missed_r", "stop_quality", "trail_quality", "benchmark_beat")},
    }

    def test_every_field_has_a_column(self):
        L = Ledger(":memory:")
        cols = {t: {r[1] for r in L.conn.execute(f"PRAGMA table_info({t})")}
                for t in ("cards", "evidence", "strength_scores", "daily", "exits", "finals")}
        L.close()
        for field, places in self.FIELDS.items():
            for t, c in places:
                with self.subTest(field=field, column=c):
                    self.assertIn(c, cols[t])


if __name__ == "__main__":
    unittest.main()
