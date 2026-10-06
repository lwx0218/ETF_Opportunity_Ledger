"""固定阈值、排序、双盲及只读性；通过 Ledger 正规方法建立合成台账。"""
import json
import sqlite3

from src.ledger import read
from src.ledger.store import mechanical_score
from src.scoring.review import counterfactual, review_report
from tests.ledger.test_ledger import Base, T0, card


class Review(Base):
    def closed(self, r=-0.2, final_at="2026-12-21T16:00", manual=False):
        cid = self.run_to_exit(reason="手动" if manual else "移动止盈", r=r,
                               manual="合成手动理由" if manual else None)
        self.track(cid)
        self.at(final_at).L.finalize(cid, post_exit_return_pct=0, post_exit_r=0,
            final_score=mechanical_score(self.L.card(cid), self.cols("exits", cid)), missed_r=0,
            stop_quality=0, trail_quality=None if manual else 0, benchmark_beat=0)
        return cid

    def alert(self, name):
        return next(a for a in review_report(self.L.conn)["alerts"] if a["id"] == name)

    def test_empty_report_does_not_infer_zero_performance_or_approval(self):
        report = review_report(self.L.conn)
        self.assertEqual(report["calibration"]["owner"], [])
        self.assertTrue(all(a["status"] == "insufficient" and a["value"] is None for a in report["alerts"]))
        self.assertEqual(report["allowed_decisions"], ["继续", "停止", "重开新版本"])
        self.assertFalse(report["automatic_actions"])
        self.assertEqual({p["id"] for p in report["pending"]},
                         {"random_container", "quarterly_reversal", "annual_review", "universe_change"})

    def test_mean_r_requires_twenty_closed_and_includes_boundary(self):
        for _ in range(19):
            self.closed()
        before = self.alert("last_20_mean_r")
        self.assertEqual((before["n"], before["value"], before["triggered"]), (19, None, None))
        self.closed()
        after = self.alert("last_20_mean_r")
        self.assertEqual((after["n"], after["value"], after["triggered"]), (20, -0.2, True))
        self.assertEqual(after["threshold"], -0.2)

    def test_recent_window_sorts_finalization_then_id_not_creation_or_exit(self):
        latest = self.closed(r=2, final_at="2026-12-22T16:00")
        for _ in range(19):
            self.closed(r=0)
        oldest = self.closed(r=-100, final_at="2026-12-18T16:00")
        alert = self.alert("last_20_mean_r")
        ids = [r["card_id"] for r in alert["facts"]]
        self.assertEqual(ids[0], latest)
        self.assertEqual(ids[1:], sorted(ids[1:], reverse=True))
        self.assertNotIn(oldest, ids)
        self.assertAlmostEqual(alert["value"], 0.1)
        self.assertFalse(alert["triggered"])

    def test_only_finalized_cards_enter_twenty_card_window(self):
        for _ in range(19):
            self.closed()
        self.run_to_exit(r=-10)
        self.at(T0).L.void(self.make(evidence=[]), "合成未进場作废")
        self.assertEqual(self.alert("last_20_mean_r")["n"], 19)

    def test_manual_threshold_is_strict_and_counts_all_exits(self):
        for i in range(10):
            self.run_to_exit(reason="手动" if i < 3 else "移动止盈", manual="合成理由" if i < 3 else None)
        at_boundary = self.alert("manual_exit_share")
        self.assertEqual((at_boundary["value"], at_boundary["triggered"]), (0.3, False))
        self.assertEqual(at_boundary["facts"], {"manual_count": 3, "exited_count": 10})
        self.run_to_exit(reason="手动", manual="合成理由")
        self.assertTrue(self.alert("manual_exit_share")["triggered"])

    def test_owner_calibration_reuses_terminal_denominator_and_small_sample_notice(self):
        for _ in range(30):
            cid = self.at(T0).make(evidence=[])
            self.L.owner_score(cid, 3, "Owner 合成独立判断")
            self.L.void(cid, "合成作废")
            if _ == 28:
                bucket = review_report(self.L.conn)["calibration"]["owner"][0]
                self.assertFalse(bucket["enough"])
                self.assertEqual(bucket["interpretation"], "样本不足，不下结论")
        bucket = review_report(self.L.conn)["calibration"]["owner"][0]
        self.assertTrue(bucket["enough"])
        self.assertEqual({k: v for k, v in bucket.items() if k != "interpretation"}, read.calibration(self.L.conn, "owner")[0])
        self.assertEqual((bucket["n"], bucket["voided"], bucket["closed"]), (30, 30, 0))

    def test_agent_score_and_reason_never_disclosed_even_void_before_owner_deadline(self):
        cid = self.L.create_card(card(evidence_status="已检索无证据"), [],
                                 {"score": 5, "reason": "PRIVATE_AGENT_REASON", "scored_at": T0})
        self.L.void(cid, "仍在独立评分窗口")
        payload = json.dumps(review_report(self.L.conn), ensure_ascii=False)
        self.assertNotIn("PRIVATE_AGENT_REASON", payload)
        self.assertNotIn("4–5", payload)
        self.assertEqual(review_report(self.L.conn)["calibration"]["agent"]["status"], "held_until_review")

    def test_unscored_cards_remain_counted_outside_owner_buckets(self):
        first, second = self.make(evidence=[]), self.make(evidence=[])
        self.L.void(first, "尚未评分的作废卡仍需计数")
        self.assertEqual(review_report(self.L.conn)["calibration"]["unscored"], {"total": 2, "n": 1, "open": 1})
        self.L.owner_score(second, 1, "独立评分后转入自己的桶")
        report = review_report(self.L.conn)["calibration"]
        self.assertEqual(report["unscored"], {"total": 1, "n": 1, "open": 0})
        self.assertEqual(report["owner"][0]["open"], 1)

    def test_counterfactual_returns_frozen_and_recorded_values_without_inferred_returns(self):
        cid = self.run_to_exit(r=0.75, excess=1.25)
        result = counterfactual(self.L.conn, cid)
        self.assertEqual(result["frozen"], {"date": "2026-10-09", "equal_weight_level": 1.0,
                                           "hs300_level": 5000.0, "container_price": 10.0})
        self.assertEqual(result["recorded_result"], {"benchmark": "等权组合", "entry_date": "2026-10-12",
                         "exit_date": "2026-11-20", "realized_excess_pct": 1.25, "realized_r": 0.75})
        self.assertTrue(all(r["status"] == "pending" for r in result["comparisons"]))
        self.assertNotIn("return_pct", json.dumps(result))

    def test_counterfactual_candidate_and_missing_card(self):
        cid = self.make()
        self.assertIsNone(counterfactual(self.L.conn, cid)["recorded_result"])
        self.assertIsNone(counterfactual(self.L.conn, "T-2026-999"))

    def test_read_functions_work_with_query_only_without_changing_database(self):
        cid = self.make()
        before = self.L.conn.total_changes
        self.L.conn.execute("PRAGMA query_only = ON")
        review_report(self.L.conn)
        counterfactual(self.L.conn, cid)
        self.assertEqual(before, self.L.conn.total_changes)
        with self.assertRaises(sqlite3.OperationalError):
            self.L.conn.execute("CREATE TABLE accidental_write(x)")
