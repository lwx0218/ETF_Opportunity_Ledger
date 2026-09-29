"""卡片存储：锁死字段、§2.5 每条禁令、REPLACE 绕过、时钟、作废重建、分母。只用内存数据库、可控时钟与仓库里的固定源清单。

运行：python -m unittest discover -s tests -t .
"""
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ledger.store import CARD_FIELDS, Ledger, LedgerError, mechanical_score   # noqa: E402

A_SRC, B_SRC, C_SRC = "ENE-EIA-WPSR", "GEO-UKMTO-WARN", "ENE-OPEC-MOMR"
T0 = "2026-10-09T16:05"          # 周五收盘后立卡；下一交易日 10-12（周一）09:30 为 owner 截止


def card(**over):
    c = dict(created_at=T0, close_date="2026-10-09", container="半导体", instrument_code="512480",
             instrument_name="国联安中证全指半导体ETF", research_index_code="H30184", trigger_type="事件驱动",
             state_at_entry="BNB", thesis="库存超预期下降，一手数据确认", evidence_status="有证据", expectation_horizon_days=20,
             thesis_inval_source_id=A_SRC, thesis_inval_deadline="2026-11-06", thesis_inval_statement="11 月 6 日前库存转增即失效",
             expectation_target_excess_pct=5.0, expectation_benchmark="等权组合", invalidation_price=9.2,
             invalidation_atr_value=0.4, invalidation_atr_multiple=2.0, r_unit_per_share=0.8, r_unit_pct_of_nav=0.5,
             planned_size_pct=6.25, cf_ew_level=1.0, cf_hs300_level=5000.0, cf_container_price=10.0,
             crowd_rs_1m_rank=2, crowd_premium_pct=None, owner_score_deadline="2026-10-12T09:30")
    c.update(over)
    return c


RULE = dict(trigger_type="恐慌下轨", state_at_entry="NEUTRAL", thesis="月末 z=-2.40 ≤ -2，恐慌下轨", evidence_status="未检索",
            scoring_rule="schema-v1.1-R", expectation_horizon_days=None, expectation_target_excess_pct=None,
            expectation_target_r=2, expectation_benchmark="等权组合",
            thesis_inval_source_id=None, thesis_inval_deadline=None, thesis_inval_statement=None)   # 规则卡字段（v1.1-a / c）


def ev(**over):
    e = dict(source_id=A_SRC, published_at="2026-10-08T22:30", summary="EIA 商业原油库存降幅大于预期",
             url="https://www.eia.gov/petroleum/supply/weekly/", first_seen_at="2026-10-08T22:40",
             available_at="2026-10-08T22:30", snapshot_path="snapshots/2026-10-08/psw00.pdf", snapshot_sha256="a" * 64)
    e.update(over)
    return e


def bdays_after(d: str, n: int) -> list[str]:
    out, x = [], date.fromisoformat(d)
    while len(out) < n:
        x += timedelta(days=1)
        if x.weekday() < 5:
            out.append(x.isoformat())
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.t = T0
        self.L = Ledger(":memory:", clock=lambda: self.t, replay=True)
        self.addCleanup(self.L.close)

    def at(self, t):
        self.t = t
        return self

    def make(self, evidence=None, **over):
        if evidence == [] and "evidence_status" not in over:
            over["evidence_status"] = "已检索无证据"
        c = card(**over)
        self.t = max(self.t, c["created_at"])
        agent = None if c["evidence_status"] == "未检索" else dict(score=3, reason="一手数据，方向与论点一致", scored_at=c["created_at"])
        return self.L.create_card(c, [ev()] if evidence is None else evidence, agent)

    def make_rule_card(self, **over):
        """规则卡（恐慌下轨）：未检索、不写 agent 分、菜单第 2 项。"""
        return self.make(evidence=[], **{**RULE, **over})

    def raw(self, sql, *args):
        self.L.conn.execute(sql, args)

    def rejects(self, sql, *args, msg=""):
        with self.assertRaisesRegex(sqlite3.DatabaseError, msg):
            self.raw(sql, *args)

    def cols(self, table, cid):
        q = "SELECT * FROM cards WHERE id = ?" if table == "cards" else f"SELECT * FROM {table} WHERE card_id = ?"
        return dict(self.L.conn.execute(q, (cid,)).fetchone())

    def replace(self, table, row, **change):
        r = {**row, **change}
        sql = f"({', '.join(r)}) VALUES ({', '.join('?' * len(r))})"
        self.rejects(f"INSERT OR REPLACE INTO {table} {sql}", *r.values(), msg="已")
        self.rejects(f"REPLACE INTO {table} {sql}", *r.values(), msg="已")

    def run_to_exit(self, reason="移动止盈", r=1.8, excess=6.0, manual=None):
        cid = self.make()
        self.at("2026-10-12T09:35").L.enter(cid, "2026-10-12", 10.05, 6.25)
        self.at("2026-10-12T16:00").L.append_daily(cid, dict(date="2026-10-12", close=10.2, state="TREND_UP", r_current=0.19, stop_now=9.2))
        self.at("2026-11-20T16:00").L.exit(cid, exit_date="2026-11-20", exit_price=11.5, exit_reason=reason, manual_reason=manual,
                                           realized_r=r, realized_excess_pct=excess, holding_days=28)
        return cid

    def track(self, cid, n=20, start="2026-11-20"):
        for d in bdays_after(start, n):
            self.at(f"{d}T16:00").L.append_daily(cid, dict(date=d, close=11.6, state="NEUTRAL"))


class Creation(Base):
    def test_create_and_read_back(self):
        cid = self.make()
        self.assertEqual(cid, "T-2026-001")
        self.assertEqual(self.L.status(cid), "候选")
        c = self.L.card(cid)
        self.assertEqual((c["scoring_rule"], c["tracking_days"], c["recorded_at"]), ("schema-v1-§3", 20, T0))
        self.assertEqual(self.L.evidence(cid)[0]["source_grade"], "A")
        self.assertEqual(self.make(), "T-2026-002")

    def test_empty_evidence_is_legal(self):
        self.assertEqual(self.L.evidence(self.make(evidence=[])), [])

    def test_rejected_evidence_rolls_back_whole_card(self):
        for bad, msg in [(dict(source_id="NOT-IN-LIST"), "固定源"), (dict(source_id=C_SRC), "A 或 B"),
                         (dict(available_at="2026-10-09T16:06", first_seen_at="2026-10-09T16:00"), "available_at"),
                         (dict(first_seen_at="2026-10-09T16:10"), "first_seen_at"),
                         (dict(available_at="2026-10-07T00:00"), "CHECK"),                 # 早于发布
                         (dict(published_at="2026-10-08 22:30"), "CHECK"),                 # 空格分隔绕不过比较
                         (dict(snapshot_sha256="xyz"), "CHECK")]:
            with self.subTest(msg), self.assertRaisesRegex(LedgerError, msg):
                self.make(evidence=[ev(**bad)])
        self.assertEqual(self.L.conn.execute("SELECT count(*) FROM cards").fetchone()[0], 0)

    def test_b_grade_source_is_accepted(self):
        self.make(evidence=[ev(source_id=B_SRC, published_at="2026-10-08", available_at="2026-10-09T00:00")])

    def test_field_checks(self):
        cases = [(dict(thesis="长" * 81), "CHECK"), (dict(created_at="2026-10-09T14:59"), "CHECK"),
                 (dict(created_at="2026-11-31T16:00", close_date="2026-11-27", owner_score_deadline="2026-12-01T09:30"), "CHECK"),   # 11-31 不存在
                 (dict(scoring_rule="自由填写"), "CHECK"), (dict(expectation_benchmark="标的自身"), "CHECK"),
                 (dict(thesis_inval_source_id=None, thesis_inval_deadline=None, thesis_inval_statement=None), "CHECK"),   # A3：事件卡缺论点失效条件
                 (dict(trigger_type="形态突破"), "CHECK"),                         # 规则卡不带论点失效条件、也不能是检索过的卡
                 (dict(thesis_inval_source_id=C_SRC, thesis_inval_deadline="2026-11-01",
                       thesis_inval_statement="11 月 1 日前 OPEC 宣布增产即失效"), "A / B"),
                 (dict(owner_score_deadline="2026-10-12T10:00"), "CHECK"),        # 截止必须是开盘 09:30
                 (dict(owner_score_deadline="2026-10-30T09:30"), "CHECK"),        # 超过 14 天不是「下一交易日」
                 (dict(state_at_entry="启动"), "CHECK"), (dict(planned_size_pct=30), "CHECK"),
                 (dict(tracking_days=5), "CHECK"),                                 # A2 统一 20
                 (dict(invalidation_price="abc"), "CHECK"), (dict(expectation_target_excess_pct="−3.0"), "CHECK")]
        for over, msg in cases:
            with self.subTest(over), self.assertRaisesRegex(LedgerError, msg):
                self.t = T0
                self.make(**over)

    def test_cannot_create_after_next_open_or_in_future(self):
        with self.assertRaisesRegex(LedgerError, "已过下一次开盘"):
            self.at("2026-10-12T09:30").make()                                  # 数据库时钟已过截止：不能补立
        self.t = "2026-10-09T16:00"
        with self.assertRaisesRegex(LedgerError, "晚于当前时刻"):
            self.L.create_card(card(), [ev()], dict(score=3, reason="x", scored_at=T0))

    def test_event_card(self):
        cid = self.make(trigger_type="事件驱动", thesis_inval_source_id=A_SRC, thesis_inval_deadline="2026-10-22",
                        thesis_inval_statement="10 月 22 日前 EIA 周报显示库存转为增加即失效")
        self.assertEqual(self.L.card(cid)["thesis_inval_source_id"], A_SRC)

    def test_scan_key_makes_reruns_idempotent(self):
        self.make(scan_key="2026-10-09|半导体|形态突破")
        with self.assertRaisesRegex(LedgerError, "scan_key"):
            self.make(scan_key="2026-10-09|半导体|形态突破")
        self.assertEqual(self.L.find_by_scan_key("2026-10-09|半导体|形态突破"), "T-2026-001")

    def test_seal_requires_agent_score_and_raw_connection_fails_closed(self):
        c = card(id="T-2026-900", scoring_rule="schema-v1-§3", recorded_at=T0)
        self.raw(f"INSERT INTO cards ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", *c.values())
        self.rejects("UPDATE cards SET sealed = 1 WHERE id = 'T-2026-900'", msg="agent")
        bare = sqlite3.connect(":memory:")                                   # 没注册 ledger_now() 的裸连接
        bare.executescript((ROOT / "src" / "ledger" / "schema.sql").read_text(encoding="utf-8"))
        with self.assertRaises(sqlite3.OperationalError):
            bare.execute(f"INSERT INTO cards ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", list(c.values()))
        bare.close()

    def test_cannot_insert_sealed_card_directly(self):
        c = card(id="T-2026-901", scoring_rule="schema-v1-§3", sealed=1, recorded_at=T0)
        self.rejects(f"INSERT INTO cards ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", *c.values(), msg="未封存")


class SchemaV11(Base):
    """docs/etf-card-schema-v1.md v1.1 补充：evidence_status、菜单第 2 项（R 倍数）。"""

    def test_unsearched_card_has_no_agent_score_and_no_evidence(self):
        cid = self.make_rule_card()
        self.assertEqual(self.L.status(cid), "候选")
        self.assertIsNone(self.L.conn.execute("SELECT agent_strength FROM card_status WHERE id = ?", (cid,)).fetchone()[0])
        with self.assertRaisesRegex(LedgerError, "未检索的卡不写 agent"):
            self.L.create_card(card(**RULE), [], dict(score=0, reason="机械", scored_at=T0))
        with self.assertRaisesRegex(LedgerError, "只有 evidence_status = 有证据"):
            self.L.create_card(card(**RULE), [ev()], None)

    def test_searched_cards_need_agent_score_and_matching_evidence(self):
        with self.assertRaisesRegex(LedgerError, "agent"):
            self.L.create_card(card(evidence_status="已检索无证据"), [], None)
        with self.assertRaisesRegex(LedgerError, "至少要有一条证据"):
            self.L.create_card(card(evidence_status="有证据"), [], dict(score=1, reason="x", scored_at=T0))
        with self.assertRaisesRegex(LedgerError, "只有 evidence_status = 有证据"):
            self.make(evidence=[ev()], evidence_status="已检索无证据")
        self.assertEqual(self.L.card(self.make(evidence=[]))["evidence_status"], "已检索无证据")

    def test_evidence_status_matches_trigger_type(self):
        """v1.1-a：机械卡 = 未检索；事件卡由起草人检索后填 已检索*。绕过 Python 直接写也拒。"""
        with self.assertRaisesRegex(LedgerError, "CHECK"):
            self.L.create_card(card(evidence_status="未检索"), [], None)                      # 事件卡不能未检索
        with self.assertRaisesRegex(LedgerError, "CHECK"):
            self.L.create_card(card(**{**RULE, "evidence_status": "有证据"}), [ev()], dict(score=3, reason="x", scored_at=T0))

    def test_seal_only_in_the_creating_transaction(self):
        """未封存的卡不进分母：不能先插一批、看完行情只封存赢家（复核 P6b-2）。"""
        c = card(**RULE, id="T-2026-902", recorded_at=T0)
        self.raw(f"INSERT INTO cards ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", *c.values())
        self.t = "2026-10-09T16:30"
        self.rejects("UPDATE cards SET sealed = 1 WHERE id = 'T-2026-902'", msg="同一事务")
        self.t = "2026-10-20T16:00"
        self.rejects("UPDATE cards SET sealed = 1 WHERE id = 'T-2026-902'", msg="同一事务|已过下一次开盘")
        self.assertEqual(self.L.summary()["denominator"], 0)

    def test_long_holiday_deadline(self):
        """有交易日历时长假前一天的截止可达 11 天（春节）；存储层上限 14 天。"""
        cid = self.make(owner_score_deadline="2026-10-20T09:30")
        self.assertEqual(self.L.card(cid)["owner_score_deadline"], "2026-10-20T09:30")

    def test_menu_two_constraints(self):
        bad = [dict(trigger_type="事件驱动", evidence_status="已检索无证据", thesis_inval_source_id=A_SRC,
                    thesis_inval_deadline="2026-10-22", thesis_inval_statement="到期未兑现即失效"),   # 事件卡只能用菜单第 1 项
               dict(expectation_target_r=3), dict(expectation_benchmark="沪深300"), dict(expectation_horizon_days=20)]
        for over in bad:
            with self.subTest(over), self.assertRaisesRegex(LedgerError, "CHECK"):
                self.make_rule_card(**over)
        with self.assertRaisesRegex(LedgerError, "CHECK"):          # 菜单第 1 项缺 horizon
            self.make(expectation_horizon_days=None)

    def test_menu_two_mechanical_score(self):
        cases = [(-1.2, "失效位", "证伪"), (-1.0, "手动", "证伪"), (-0.5, "手动", "未达"), (0.0, "论点作废", "未达"),
                 (1.4, "移动止盈", "部分"), (2.0, "移动止盈", "达标"), (3.1, "移动止盈", "达标")]
        for r, reason, want in cases:
            with self.subTest(r=r):
                self.assertEqual(mechanical_score(reason, 99.0, None, "schema-v1.1-R", r, 2), want)
        self.t = T0
        cid = self.make_rule_card()
        self.at("2026-10-12T09:35").L.enter(cid, "2026-10-12", 10.05, 6.25)
        self.at("2026-11-20T16:00").L.exit(cid, exit_date="2026-11-20", exit_price=11.0, exit_reason="移动止盈", manual_reason=None,
                                           realized_r=1.4, realized_excess_pct=50.0, holding_days=28)
        self.track(cid)
        kw = dict(post_exit_return_pct=0, post_exit_r=0, missed_r=0, stop_quality=0, trail_quality=0, benchmark_beat=1)
        with self.assertRaisesRegex(LedgerError, "机械"):
            self.L.finalize(cid, final_score="达标", **kw)                 # 超额再高，菜单第 2 项也只看 R
        self.L.finalize(cid, final_score="部分", **kw)

    def test_calibration_puts_unsearched_cards_in_their_own_bucket(self):
        self.make_rule_card(scan_key="a")
        self.make()
        cal = {c["bucket"]: c for c in self.L.calibration("agent")}
        self.assertEqual(set(cal), {"未检索", "2–3"})
        self.assertEqual((cal["未检索"]["open"], cal["2–3"]["open"]), (1, 1))

    def test_old_schema_db_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "old.sqlite"
            L = Ledger(db, clock=lambda: T0, replay=True)
            L.conn.execute("DROP TRIGGER ledger_meta_no_delete")
            L.conn.execute("DELETE FROM ledger_meta WHERE key = 'schema'")          # 模拟 v1 代码建的库
            L.close()
            with self.assertRaisesRegex(LedgerError, "schema 是 v1"):
                Ledger(db, clock=lambda: T0, replay=True)
            # 真正的旧库（v1 的 cards 没有 evidence_status）：拒绝，且一个字节都不改
            old = Path(d) / "older.sqlite"
            c = sqlite3.connect(old)
            c.executescript("CREATE TABLE cards (id TEXT PRIMARY KEY, thesis TEXT); CREATE TABLE ledger_meta (key TEXT, value TEXT);"
                            "INSERT INTO ledger_meta VALUES ('clock', 'real');")
            c.close()
            before = old.read_bytes()
            with self.assertRaisesRegex(LedgerError, "需迁移"):
                Ledger(old)
            self.assertEqual(old.read_bytes(), before)


class Section25(Base):
    """schema §2.5 明令禁止——每条一个失败测试（UPDATE、DELETE、REPLACE 三种写法都试）。"""

    def test_no_evidence_added_after_creation(self):
        cid = self.make()
        with self.assertRaisesRegex(LedgerError, "事后添加"):
            self.L._tx(lambda: self.L._insert("evidence", {"card_id": cid, "seq": 2, "source_grade": "A", **ev()}, stamp=False))

    def test_no_evidence_modified(self):
        cid = self.make()
        self.rejects("UPDATE evidence SET summary = '改过' WHERE card_id = ?", cid)
        self.replace("evidence", self.cols("evidence", cid), summary="改过")

    def test_frozen_fields_cannot_change(self):
        cid = self.make()
        types = {r[1]: r[2] for r in self.L.conn.execute("PRAGMA table_info(cards)")}
        for col in CARD_FIELDS + ("recorded_at",):      # 含 expectation / invalidation / scoring_rule 全部列
            change = f"coalesce({col}, '') || 'x'" if types[col] == "TEXT" else f"coalesce({col}, 0) + 1"
            with self.subTest(col):
                self.rejects(f"UPDATE cards SET {col} = {change} WHERE id = ?", cid, msg="锁死")     # 触发器拒绝，不是 CHECK
        self.rejects("UPDATE cards SET sealed = 0 WHERE id = ?", cid, msg="锁死")
        self.replace("cards", self.cols("cards", cid), thesis="改过的论点", expectation_target_excess_pct=-100.0, sealed=0)
        self.assertEqual(self.L.card(cid)["expectation_target_excess_pct"], 5.0)
        self.assertEqual(self.L.summary()["denominator"], 1)

    def test_evidence_strength_locked(self):
        cid = self.make()
        self.rejects("UPDATE strength_scores SET score = 5 WHERE card_id = ?", cid)
        self.replace("strength_scores", self.cols("strength_scores", cid), score=5)
        self.at("2026-10-10T20:00").L.owner_score(cid, 2, "只有一条库存数据")
        with self.assertRaises(LedgerError):
            self.L.owner_score(cid, 4, "改主意")
        owner = dict(self.L.conn.execute("SELECT * FROM strength_scores WHERE card_id = ? AND rater = 'owner'", (cid,)).fetchone())
        self.replace("strength_scores", owner, score=5)
        self.rejects("UPDATE strength_scores SET score = 5 WHERE card_id = ? AND rater = 'owner'", cid)

    def test_owner_deadline_uses_database_clock(self):
        cid = self.make()
        with self.assertRaisesRegex(LedgerError, "截止"):
            self.at("2026-10-12T09:30").L.owner_score(cid, 2, "晚了")
        # 调用方写一个截止前的 scored_at 也没用：判定看数据库时钟
        with self.assertRaisesRegex(LedgerError, "截止"):
            self.L._tx(lambda: self.L._insert("strength_scores", {"card_id": cid, "rater": "owner", "score": 2, "reason": "倒填",
                                                                   "scored_at": "2026-10-10T08:00"}))
        self.assertIsNone(self.L.conn.execute("SELECT owner_strength FROM card_status WHERE id = ?", (cid,)).fetchone()[0])

    def test_no_card_deleted_including_voided(self):
        a, b = self.make(), self.make()
        self.at("2026-10-12T09:00").L.void(b, "未进场而失效")
        for cid in (a, b):
            self.rejects("DELETE FROM cards WHERE id = ?", cid)
        for t in ("evidence", "strength_scores", "voids", "fixed_sources", "source_loads"):
            self.rejects(f"DELETE FROM {t}")
        # 借 UNIQUE(supersedes) 冲突让 REPLACE 隐式删掉别的卡：也不行
        self.t = "2026-10-12T09:05"
        c = self.L.create_card(card(supersedes=b, created_at="2026-10-12T09:05", evidence_status="已检索无证据"), [],
                               dict(score=1, reason="重建", scored_at="2026-10-12T09:05"))
        row = {**self.cols("cards", c), "id": "T-2026-777", "sealed": 0}
        self.rejects(f"INSERT OR REPLACE INTO cards ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values(), msg="取代")
        self.assertEqual(self.L.summary()["denominator"], 3)

    def test_correction_only_by_void_and_supersede(self):
        old = self.make()
        with self.assertRaisesRegex(LedgerError, "supersedes"):
            self.make(supersedes=old)                                       # 旧卡未作废
        self.at("2026-10-09T16:30").L.void(old, "论点写错，重建")
        with self.assertRaisesRegex(LedgerError, "supersedes"):
            self.make(supersedes=old, created_at="2026-10-09T16:20")         # 新卡早于作废时刻
        new = self.make(supersedes=old, created_at="2026-10-09T16:31", thesis="修正后的论点", invalidation_price=9.0)
        with self.assertRaisesRegex(LedgerError, "supersedes"):
            self.make(supersedes=old, created_at="2026-10-09T16:40")         # 一张旧卡只能被取代一次
        s = self.L.summary()
        self.assertEqual((s["denominator"], s["by_status"], s["superseded"]), (2, {"作废": 1, "候选": 1}, 1))
        self.assertEqual(self.L.card(new)["supersedes"], old)


class Lifecycle(Base):
    def test_full_path_and_mechanical_score(self):
        cid = self.run_to_exit()
        self.assertEqual(self.L.status(cid), "过去")
        kw = dict(post_exit_return_pct=2.0, post_exit_r=0.5, missed_r=0.3, stop_quality=0, trail_quality=1, benchmark_beat=1)
        with self.assertRaisesRegex(LedgerError, "跟踪期未满"):
            self.L.finalize(cid, final_score="达标", **kw)
        self.track(cid)
        with self.assertRaisesRegex(LedgerError, "机械"):
            self.L.finalize(cid, final_score="部分", **kw)
        self.L.finalize(cid, final_score="达标", **kw)
        self.assertEqual(self.L.status(cid), "已结")
        for t in ("entries", "daily", "exits", "finals"):
            self.rejects(f"UPDATE {t} SET recorded_at = 'x' WHERE card_id = ?", cid)
            self.rejects(f"DELETE FROM {t} WHERE card_id = ?", cid)
        for t in ("entries", "exits", "finals"):
            self.replace(t, self.cols(t, cid), recorded_at=self.t)
        with self.assertRaisesRegex(LedgerError, "已跟踪期满"):
            self.at("2026-12-31T16:00").L.append_daily(cid, dict(date="2026-12-31", close=12, state="NEUTRAL"))

    def test_replace_cannot_rewrite_outcomes(self):
        cid = self.run_to_exit(reason="失效位", r=-1.2, excess=-4.0)
        self.replace("entries", self.cols("entries", cid), entry_price=7.0)
        self.replace("exits", self.cols("exits", cid), exit_reason="移动止盈", realized_r=2.5)
        self.assertEqual(self.cols("exits", cid)["realized_r"], -1.2)

    def test_mechanical_score_rules(self):
        self.assertEqual(mechanical_score("失效位", 10.0, 5.0), "证伪")
        self.assertEqual(mechanical_score("移动止盈", 5.0, 5.0), "达标")
        self.assertEqual(mechanical_score("跟踪期满", 0.1, 5.0), "部分")
        self.assertEqual(mechanical_score("手动", 0.0, 5.0), "未达")

    def test_stop_exit_scores_falsified(self):
        cid = self.run_to_exit(reason="失效位", r=-1.05, excess=-4.0)
        self.track(cid)
        self.L.finalize(cid, post_exit_return_pct=8.0, post_exit_r=1.2, final_score="证伪", missed_r=1.2,
                        stop_quality=1, trail_quality=None, benchmark_beat=0)

    def test_manual_exit_needs_reason(self):
        with self.assertRaises(LedgerError):
            self.run_to_exit(reason="手动")
        self.t = T0
        cid = self.run_to_exit(reason="手动", manual="临停，流动性不足")
        self.assertEqual(self.L.summary()["manual_exit_share"], 1.0)
        self.assertEqual(self.L.status(cid), "过去")

    def test_time_and_order_rules(self):
        cid = self.make()
        with self.assertRaisesRegex(LedgerError, "没有进场"):
            self.L.exit(cid, exit_date="2026-10-09", exit_price=10, exit_reason="失效位", realized_r=-1, realized_excess_pct=-3, holding_days=0)
        with self.assertRaisesRegex(LedgerError, "晚于当前日期"):
            self.L.enter(cid, "2026-10-12", 10.0, 5)                         # 数据库时钟还在 10-09
        with self.assertRaisesRegex(LedgerError, "不高于失效位"):
            self.at("2026-10-12T09:35").L.enter(cid, "2026-10-12", 9.1, 5)
        self.L.enter(cid, "2026-10-12", 10.0, 5)
        with self.assertRaises(LedgerError):
            self.L.enter(cid, "2026-10-13", 10.0, 5)                       # 只能进场一次
        self.at("2026-10-13T16:00").L.append_daily(cid, dict(date="2026-10-13", close=10.1, state="XB"))
        with self.assertRaisesRegex(LedgerError, "向后追加"):
            self.L.append_daily(cid, dict(date="2026-10-12", close=10.0, state="XB"))
        with self.assertRaisesRegex(LedgerError, "晚于当前日期"):
            self.L.append_daily(cid, dict(date="2026-10-14", close=10.0, state="XB"))
        with self.assertRaisesRegex(LedgerError, "CHECK"):
            self.at("2026-10-31T16:00").L.append_daily(cid, dict(date="2026-10-1x", close=10.0, state="XB"))   # 非日期

    def test_owner_never_sees_the_trade(self):
        # 截止写得再晚，进场也不能早于截止那次开盘：owner 打分时这笔交易还没发生
        cid = self.at("2026-10-13T16:00").make(created_at="2026-10-13T16:00", close_date="2026-10-13",
                                               owner_score_deadline="2026-10-23T09:30")
        with self.assertRaisesRegex(LedgerError, "倒填"):
            self.at("2026-10-14T09:35").L.enter(cid, "2026-10-14", 10.0, 5)

    def test_morning_confirmed_card_enters_same_day(self):
        cid = self.at("2026-10-12T09:00").make(created_at="2026-10-12T09:00", close_date="2026-10-09")   # 周五信号，周一早盘确认
        self.at("2026-10-12T09:35").L.enter(cid, "2026-10-12", 10.0, 5)
        self.assertEqual(self.L.status(cid), "当下")

    def test_cannot_create_card_after_seeing_later_prices(self):
        with self.assertRaisesRegex(LedgerError, "CHECK"):          # 10-13 的信号拖到 10-22 才立
            self.at("2026-10-22T20:00").make(created_at="2026-10-22T20:00", close_date="2026-10-13",
                                             owner_score_deadline="2026-10-23T09:30")

    def test_infinite_values_rejected(self):
        with self.assertRaisesRegex(LedgerError, "CHECK"):
            self.make(expectation_target_excess_pct=float("inf"))

    def test_no_backdated_entry(self):
        # 10-19 收盘后才立卡，不能用 10-19 当天或更早的已知价格倒填进场
        cid = self.at("2026-10-19T16:00").make(created_at="2026-10-19T16:00", close_date="2026-10-19",
                                               owner_score_deadline="2026-10-20T09:30")
        with self.assertRaisesRegex(LedgerError, "倒填"):
            self.at("2026-10-20T10:00").L.enter(cid, "2026-10-19", 10.0, 5)

    def test_void_rules(self):
        cand = self.make()
        self.at("2026-10-12T09:31").L.void(cand, "未进场而失效：次日跳空低于失效位")
        self.assertEqual(self.L.status(cand), "作废")
        with self.assertRaisesRegex(LedgerError, "作废"):
            self.L.enter(cand, "2026-10-12", 10.0, 5)
        with self.assertRaises(LedgerError):
            self.L.void(cand, "再作废一次")
        self.replace("voids", self.cols("voids", cand), reason="改个理由")
        self.t = T0
        live = self.make()
        self.at("2026-10-12T09:35").L.enter(live, "2026-10-12", 10.05, 6.25)
        with self.assertRaisesRegex(LedgerError, "只有未进场的候选"):
            self.L.void(live, "亏了不想要")                                 # 已进场：只能按论点作废 / 手动出场


class Statistics(Base):
    def test_denominator_and_calibration(self):
        ids = [self.make() for _ in range(4)]
        self.at("2026-10-12T09:31").L.void(ids[0], "未进场而失效")
        self.at("2026-10-12T09:35").L.enter(ids[1], "2026-10-12", 10.0, 5)
        self.at("2026-11-10T16:00").L.exit(ids[1], exit_date="2026-11-10", exit_price=11, exit_reason="移动止盈",
                                           realized_r=1.2, realized_excess_pct=6.0, holding_days=20)
        self.track(ids[1], start="2026-11-10")
        self.L.finalize(ids[1], post_exit_return_pct=0, post_exit_r=0, final_score="达标", missed_r=0, stop_quality=0,
                        trail_quality=1, benchmark_beat=1)
        s = self.L.summary()
        self.assertEqual((s["denominator"], s["terminal"]), (4, 2))
        self.assertEqual(s["hit_rate_over_terminal"], 0.5)                  # 1 张达标 / 2 张终态（作废计入）
        cal = self.L.calibration("agent")
        self.assertEqual([(c["bucket"], c["n"], c["voided"], c["closed"], c["open"], c["hits"]) for c in cal], [("2–3", 2, 1, 1, 2, 1)])
        self.assertFalse(cal[0]["enough"])
        self.assertEqual(self.L.calibration("owner"), [])                     # owner 全部缺失

    def test_open_cards_do_not_make_a_bucket_enough(self):
        for i in range(30):
            self.make(scan_key=f"k{i}")
        cal = self.L.calibration("agent")[0]
        self.assertEqual((cal["n"], cal["open"], cal["enough"], cal["hit_rate"]), (0, 30, False, None))


class ClockMode(unittest.TestCase):
    def test_injected_clock_needs_replay_and_a_separate_db(self):
        with self.assertRaisesRegex(LedgerError, "replay=True"):
            Ledger(":memory:", clock=lambda: T0)
        from src.ledger.store import DEFAULT_DB
        with self.assertRaisesRegex(LedgerError, "正式台账库"):
            Ledger(DEFAULT_DB, clock=lambda: T0, replay=True)

    def test_db_remembers_clock_mode(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "replay.sqlite"
            Ledger(db, clock=lambda: T0, replay=True).close()
            with self.assertRaisesRegex(LedgerError, "时钟模式是 replay"):
                Ledger(db)
            Ledger(db, clock=lambda: T0, replay=True).close()


class RowidReplace(Base):
    def test_explicit_rowid_is_an_error(self):
        a = self.make()
        row = self.cols("cards", a)
        with self.assertRaises(sqlite3.DatabaseError):
            self.raw(f"INSERT OR REPLACE INTO cards (rowid, {', '.join(row)}) VALUES (1, {', '.join('?' * len(row))})",
                     *{**row, "id": "T-2026-099", "sealed": 0}.values())
        self.assertEqual(self.L.summary()["denominator"], 1)

    def test_source_versions_need_database_clock(self):
        bare = sqlite3.connect(":memory:")
        bare.executescript((ROOT / "src" / "ledger" / "schema.sql").read_text(encoding="utf-8"))
        with self.assertRaises(sqlite3.OperationalError):
            bare.execute("INSERT INTO source_loads (csv_sha256, seq, loaded_at) VALUES (?, 1, ?)", ("f" * 64, T0))
        bare.close()


class FixedSources(Base):
    def test_table_is_append_only_and_versioned(self):
        self.rejects(f"UPDATE fixed_sources SET grade = 'A' WHERE source_id = '{C_SRC}'")
        self.rejects("INSERT OR REPLACE INTO fixed_sources (source_id, csv_sha256, name, grade) "
                     "SELECT source_id, csv_sha256, name, 'A' FROM fixed_sources WHERE source_id = ?", C_SRC)
        self.assertEqual(self.L.load_sources(), 60)                           # 同一版本重复载入：不追加
        self.assertEqual(self.L.conn.execute("SELECT count(*) FROM source_loads").fetchone()[0], 1)

    def test_upgraded_list_adds_a_version(self):
        lines = (ROOT / "docs" / "etf-fixed-sources-v1.csv").read_text(encoding="utf-8-sig").splitlines()
        i = next(k for k, l in enumerate(lines) if l.startswith(C_SRC + ","))
        parts = lines[i].split(",")
        parts[4] = "B"                                                         # S2 核实后 C → B
        lines[i] = ",".join(parts)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(Path(f.name).unlink)
        self.L.sources_path = Path(f.name)
        self.L.load_sources(Path(f.name))
        self.assertEqual(self.L.conn.execute("SELECT count(*) FROM source_loads").fetchone()[0], 2)
        cid = self.make(evidence=[ev(source_id=C_SRC)])                        # 新版本里已是 B 级
        self.assertEqual(self.L.evidence(cid)[0]["source_grade"], "B")


class SchemaCoverage(unittest.TestCase):
    """docs/etf-card-schema-v1.md §2 的每个字段都有落点（表, 列）。"""
    FIELDS = {
        "id": [("cards", "id")], "created_at": [("cards", "created_at"), ("cards", "close_date")], "container": [("cards", "container")],
        "instrument": [("cards", "instrument_code"), ("cards", "instrument_name"), ("cards", "research_index_code")],
        "trigger_type": [("cards", "trigger_type")], "state_at_entry": [("cards", "state_at_entry")], "thesis": [("cards", "thesis")],
        "evidence[]": [("evidence", c) for c in ("source_id", "published_at", "summary", "url", "first_seen_at", "available_at",
                                                 "snapshot_path", "snapshot_sha256")],
        "evidence_strength": [("strength_scores", "score"), ("strength_scores", "reason"), ("strength_scores", "rater")],
        "expectation": [("cards", "expectation_horizon_days"), ("cards", "expectation_target_excess_pct"), ("cards", "expectation_target_r"),
                        ("cards", "expectation_benchmark")],
        "evidence_status": [("cards", "evidence_status")],
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
