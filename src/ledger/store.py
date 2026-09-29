"""卡片台账的 SQLite 存储。纪律在存储层（schema.sql 的 CHECK 与触发器）强制，这里只是薄封装：
Python 层的校验只为给出可读的错误，绕过它直接写 SQL 同样会被拒绝。

- 冻结：只追加的表全部拒绝 DELETE 与 UPDATE（cards 只许创建事务内 sealed 0→1）；每张表的 BEFORE INSERT 触发器
  在同键行已存在时拒绝，堵住 INSERT OR REPLACE / REPLACE INTO 的隐式删除；表都是 WITHOUT ROWID，显式写 rowid 直接报错；
  本类的连接另开 recursive_triggers 作第二道防线。
- 时钟：触发器用 ledger_now()（本类注册的数据库时钟，北京时间到分钟）判断截止与「不能写未来」；每个事务内冻结为同一时刻。
  没注册该函数的连接写不进台账行。注入时钟只用于回放：必须 replay=True，且不能是正式台账库；
  库在第一次打开时记下时钟模式（real / replay），之后用另一种模式打开即拒绝——回放的卡永远进不了正式库。
- 边界：拿到数据库文件的人仍可 DROP TRIGGER——存储层防误改和流程绕行，防不了蓄意篡改；文件应只由台账进程写入。
"""
from __future__ import annotations

import csv
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = Path(__file__).with_name("schema.sql")
FIXED_SOURCES = ROOT / "docs" / "etf-fixed-sources-v1.csv"
DEFAULT_DB = ROOT / "data" / "ledger.sqlite"          # 不入 Git（.gitignore：*.sqlite）
BEIJING = ZoneInfo("Asia/Shanghai")

APPEND_ONLY = ("cards", "evidence", "strength_scores", "entries", "daily", "exits", "finals", "voids",
               "source_loads", "fixed_sources")
CARD_FIELDS = (
    "id", "created_at", "close_date", "scan_key", "container", "instrument_code", "instrument_name", "research_index_code",
    "trigger_type", "state_at_entry", "thesis", "evidence_status", "expectation_horizon_days", "expectation_target_excess_pct",
    "expectation_target_r", "expectation_benchmark", "invalidation_price", "invalidation_atr_value", "invalidation_atr_multiple",
    "r_unit_per_share", "r_unit_pct_of_nav", "planned_size_pct", "scoring_rule", "tracking_days",
    "cf_ew_level", "cf_hs300_level", "cf_container_price", "crowd_rs_1m_rank", "crowd_rs_3m_rank",
    "crowd_vol_ratio_20", "crowd_premium_pct", "crowd_share_chg_20d", "thesis_inval_source_id",
    "thesis_inval_deadline", "thesis_inval_statement", "owner_score_deadline", "supersedes",
)
FROZEN_FIELDS = CARD_FIELDS + ("recorded_at",)
EVIDENCE_FIELDS = ("source_id", "published_at", "summary", "url", "first_seen_at", "available_at", "snapshot_path", "snapshot_sha256")
SCORING_RULE = "schema-v1-§3"          # 菜单第 1 项（按超额与期限）
SCORING_RULE_R = "schema-v1.1-R"        # 菜单第 2 项（按 R 倍数，规则卡；v1.1-c）
SCHEMA_VERSION = "v1.1-f"               # v1.1-f：出场记录加 exit_signal_close，期满先判证伪；之前建的库拒绝打开


class LedgerError(ValueError):
    """存储层拒绝了一次写入（触发器 / 约束），原因写在消息里。"""


def beijing_now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%dT%H:%M")


def _freeze_triggers() -> str:
    others = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in FROZEN_FIELDS)
    sql = [f"""CREATE TRIGGER IF NOT EXISTS cards_frozen BEFORE UPDATE ON cards
WHEN NOT (OLD.sealed = 0 AND NEW.sealed = 1) OR {others}
BEGIN SELECT RAISE(ABORT, 'cards 创建时锁死：只能作废旧卡并新建（supersedes）'); END;"""]
    for t in APPEND_ONLY:
        sql.append(f"CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t} "
                   f"BEGIN SELECT RAISE(ABORT, '{t} 不允许删除（作废卡也留在库里）'); END;")
        if t != "cards":
            sql.append(f"CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t} "
                       f"BEGIN SELECT RAISE(ABORT, '{t} 只能追加，历史行不能修改'); END;")
    return "\n".join(sql)


def mechanical_score(card: dict, exit_row: dict) -> str:
    """四档机械评分，与 finals 触发器同一口径（v1.1-f）：先判证伪——触发出场的那根收盘 < 锁定的失效位（不论出场原因标签），
    或论点作废（哪怕 R > 0）；未证伪的卡按锁定的菜单分三档：第 1 项按 realized_excess_pct 对 target_excess_pct（§3），
    第 2 项按 realized_r 对 target_r（v1.1-c），「未达」= 不大于 0（没有 −1 下限：跳空低开亏过 1R 仍是未达）。
    card 用 scoring_rule、invalidation_price、expectation_target_excess_pct、expectation_target_r；
    exit_row 用 exit_reason、exit_signal_close、realized_excess_pct、realized_r。"""
    if exit_row["exit_signal_close"] < card["invalidation_price"] or exit_row["exit_reason"] == "论点作废":
        return "证伪"
    if card["scoring_rule"] == SCORING_RULE_R:
        value, target = exit_row["realized_r"], card["expectation_target_r"]
    else:
        value, target = exit_row["realized_excess_pct"], card["expectation_target_excess_pct"]
    if value >= target:
        return "达标"
    return "部分" if value > 0 else "未达"


def read_sources_csv(path: Path = FIXED_SOURCES) -> tuple[str, dict[str, tuple[str, str]]]:
    raw = Path(path).read_bytes()
    rows = csv.DictReader(raw.decode("utf-8-sig").splitlines())
    return hashlib.sha256(raw).hexdigest(), {r["source_id"].strip(): (r["等级"].strip(), r.get("名称")) for r in rows}


class Ledger:
    def __init__(self, path: Path | str = DEFAULT_DB, sources: Path = FIXED_SOURCES, clock: Callable[[], str] | None = None,
                 replay: bool = False):
        if clock is not None and not replay:
            raise LedgerError("注入时钟只用于回放：请传 replay=True，并使用单独的回放库")
        if replay and str(path) != ":memory:" and Path(path).resolve() == DEFAULT_DB.resolve():
            raise LedgerError("回放不能写正式台账库")
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.clock, self._frozen, self.sources_path = clock or beijing_now, None, Path(sources)
        self.conn = sqlite3.connect(str(path), isolation_level=None)      # 事务由 _tx 显式控制
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("ledger_now", 0, lambda: self._frozen or self.clock())
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA recursive_triggers = ON")                # 第二道防线：REPLACE 的隐式删除也触发 DELETE 触发器
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if tables:                                    # 先查版本再建表：旧库不能被 IF NOT EXISTS 补上半套新触发器
            old = dict(self.conn.execute("SELECT key, value FROM ledger_meta").fetchall()) if "ledger_meta" in tables else {}
            if old.get("schema") != SCHEMA_VERSION:
                self.conn.close()
                raise LedgerError(f"这个库的 schema 是 {old.get('schema', 'v1')}，当前代码是 {SCHEMA_VERSION}；旧库不能直接打开，需迁移")
        self.conn.executescript(SCHEMA.read_text(encoding="utf-8") + "\n" + _freeze_triggers())
        mode = "replay" if replay else "real"
        meta = {k: v for k, v in self.conn.execute("SELECT key, value FROM ledger_meta")}
        if not meta:
            self.conn.executemany("INSERT INTO ledger_meta (key, value) VALUES (?, ?)", [("clock", mode), ("schema", SCHEMA_VERSION)])
        elif meta.get("clock") != mode:
            self.conn.close()
            raise LedgerError(f"这个库的时钟模式是 {meta.get('clock')}，不能以 {mode} 模式打开")
        self.load_sources(sources)

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------ 基础
    def now(self) -> str:
        return self._frozen or self.clock()

    def _tx(self, fn):
        self.conn.execute("BEGIN IMMEDIATE")
        self._frozen = self.clock()
        try:
            out = fn()
        except sqlite3.DatabaseError as e:
            self.conn.execute("ROLLBACK")
            raise LedgerError(str(e)) from e
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        finally:
            self._frozen = None
        self.conn.execute("COMMIT")
        return out

    def _insert(self, table: str, row: dict, stamp: bool = True):
        row = {**row, "recorded_at": self.now()} if stamp else row
        cols = list(row)
        self.conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [row[c] for c in cols])

    def load_sources(self, path: Path = FIXED_SOURCES) -> int:
        """按版本载入固定源清单：CSV 内容变了（例如 S2 把 C 级升为 B 级）就追加一个新版本，旧版本与已写入的证据不受影响。"""
        digest, rows = read_sources_csv(path)
        last = self.conn.execute("SELECT csv_sha256 FROM source_loads ORDER BY seq DESC LIMIT 1").fetchone()
        if last and last[0] == digest:
            return len(rows)
        if self.conn.execute("SELECT 1 FROM source_loads WHERE csv_sha256 = ?", (digest,)).fetchone():
            raise LedgerError("该版本清单曾经载入、之后被别的版本取代；回退清单需人工处理")

        def run():
            self.conn.execute("INSERT INTO source_loads (csv_sha256, seq, loaded_at) "
                              "VALUES (?, (SELECT coalesce(max(seq), 0) + 1 FROM source_loads), ?)", (digest, self.now()))
            self.conn.executemany("INSERT INTO fixed_sources (source_id, csv_sha256, name, grade) VALUES (?,?,?,?)",
                                  [(sid, digest, name, grade) for sid, (grade, name) in rows.items()])
        self._tx(run)
        return len(rows)

    def next_id(self, year: int) -> str:
        n = self.conn.execute("SELECT count(*) FROM cards WHERE id GLOB ?", (f"T-{year}-*",)).fetchone()[0]
        return f"T-{year}-{n + 1:03d}"

    # ------------------------------------------------------------ 生命周期
    def create_card(self, card: dict, evidence: list[dict], agent_score: dict | None) -> str:
        """一次事务：卡片（未封存）→ 证据 → agent 评分 → 封存。任何一步被拒，整张卡不入库。
        v1.1-a：evidence_status = 未检索（机械卡）时 evidence 为空、agent_score 为 None；已检索无证据时 evidence 为空；
        有证据时至少一条。后两种必须带 agent 评分。"""
        unknown = set(card) - set(CARD_FIELDS)
        if unknown:
            raise LedgerError(f"未知字段：{sorted(unknown)}")
        card = {"scoring_rule": SCORING_RULE, "tracking_days": 20, **card}
        _, csv_sources = read_sources_csv(self.sources_path)      # Python 层再对照一次仓库里的 CSV
        for ev in evidence:
            extra = set(ev) - set(EVIDENCE_FIELDS)
            if extra:
                raise LedgerError(f"证据未知字段：{sorted(extra)}")
            grade = csv_sources.get(ev.get("source_id"), ("", None))[0]
            if grade not in ("A", "B"):
                raise LedgerError(f"source_id 必须在固定源清单中且等级为 A 或 B：{ev.get('source_id')}（{grade or '不在清单'}）")

        def run():
            if "id" not in card:
                card["id"] = self.next_id(int(card["created_at"][:4]))
            self._insert("cards", card)
            for i, ev in enumerate(evidence, 1):
                self._insert("evidence", {"card_id": card["id"], "seq": i, "source_grade": csv_sources[ev["source_id"]][0], **ev},
                             stamp=False)
            if agent_score is not None:
                self._insert("strength_scores", {"card_id": card["id"], "rater": "agent", **agent_score})
            self.conn.execute("UPDATE cards SET sealed = 1 WHERE id = ?", (card["id"],))
            return card["id"]
        return self._tx(run)

    def find_by_scan_key(self, scan_key: str) -> str | None:
        r = self.conn.execute("SELECT id FROM cards WHERE scan_key = ? AND sealed = 1", (scan_key,)).fetchone()
        return r[0] if r else None

    def owner_score(self, card_id: str, score: int, reason: str) -> None:
        """owner 评分的时刻取数据库时钟，不接受调用方给的时间。"""
        self._tx(lambda: self._insert("strength_scores", {"card_id": card_id, "rater": "owner", "score": score,
                                                          "reason": reason, "scored_at": self.now()}))

    def enter(self, card_id: str, entry_date: str, entry_price: float, size_pct: float) -> None:
        self._tx(lambda: self._insert("entries", {"card_id": card_id, "entry_date": entry_date, "entry_price": entry_price,
                                                  "size_pct": size_pct}))

    def append_daily(self, card_id: str, row: dict) -> None:
        self._tx(lambda: self._insert("daily", {"card_id": card_id, **row}))

    def exit(self, card_id: str, **row) -> None:
        self._tx(lambda: self._insert("exits", {"card_id": card_id, **row}))

    def finalize(self, card_id: str, **row) -> None:
        self._tx(lambda: self._insert("finals", {"card_id": card_id, **row}))

    def void(self, card_id: str, reason: str, voided_at: str | None = None) -> None:
        self._tx(lambda: self._insert("voids", {"card_id": card_id, "reason": reason, "voided_at": voided_at or self.now()}))

    # ------------------------------------------------------------ 读
    def card(self, card_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return dict(r) if r else None

    def evidence(self, card_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM evidence WHERE card_id = ? ORDER BY seq", (card_id,))]

    def daily_rows(self, card_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM daily WHERE card_id = ? ORDER BY date", (card_id,))]

    def status(self, card_id: str) -> str | None:
        r = self.conn.execute("SELECT status FROM card_status WHERE id = ?", (card_id,)).fetchone()
        return r[0] if r else None

    def cards_in(self, *statuses: str) -> list[str]:
        q = f"SELECT id FROM card_status WHERE status IN ({', '.join('?' * len(statuses))}) ORDER BY id"
        return [r[0] for r in self.conn.execute(q, statuses)]

    def summary(self) -> dict:
        """分母 = 全部卡片（含作废、含未进场、含仍在途的）。只统计进场或已结的卡等于用结果筛样本（schema §1）。"""
        q = lambda s, *a: self.conn.execute(s, a).fetchall()   # noqa: E731
        total = q("SELECT count(*) FROM card_status")[0][0]
        by_status = {r[0]: r[1] for r in q("SELECT status, count(*) FROM card_status GROUP BY status")}
        by_score = {r[0]: r[1] for r in q("SELECT final_score, count(*) FROM card_status WHERE final_score IS NOT NULL GROUP BY final_score")}
        terminal = by_status.get("已结", 0) + by_status.get("作废", 0)
        exits = q("SELECT count(*), sum(exit_reason = '手动') FROM exits")[0]
        return {
            "denominator": total, "by_status": by_status, "by_final_score": by_score,
            "terminal": terminal,                                                      # 已结 + 作废
            "hit_rate_over_terminal": (by_score.get("达标", 0) / terminal) if terminal else None,
            "manual_exit_share": (exits[1] / exits[0]) if exits[0] else None,        # §6.4 触发器之一：> 30%
            "superseded": q("SELECT count(*) FROM cards WHERE supersedes IS NOT NULL")[0][0],
            # v1.1-f：论点作废即证伪，哪怕 R > 0（判断错了、钱对了）；这类卡单列，由 exit_reason 与 realized_r 数出来
            "falsified_thesis_void_positive_r": q("SELECT count(*) FROM card_status WHERE final_score = '证伪' "
                                                  "AND exit_reason = '论点作废' AND realized_r > 0")[0][0],
        }

    def calibration(self, rater: str = "agent") -> list[dict]:
        """schema §6.1 + v1.1-a：只用检索过的卡（已检索无证据 / 有证据）按事前 evidence_strength 分桶（0–1 / 2–3 / 4–5）；
        未检索的卡单独成一桶「未检索」，仍计入分母。n = 终态卡（已结 + 作废，作废计入分母）；达标率以 n 为分母；在途卡单列 open。"""
        col = {"agent": "agent_strength", "owner": "owner_strength"}[rater]
        rows = self.conn.execute(f"""
            SELECT CASE WHEN evidence_status = '未检索' THEN '未检索'
                        WHEN {col} <= 1 THEN '0–1' WHEN {col} <= 3 THEN '2–3' ELSE '4–5' END AS bucket,
                   sum(status IN ('已结', '作废')) AS n, sum(status = '作废') AS voided, sum(status = '已结') AS closed,
                   sum(status NOT IN ('已结', '作废')) AS open,
                   sum(final_score = '达标') AS hits, avg(CASE WHEN status = '已结' THEN realized_r END) AS mean_r_closed
              FROM card_status WHERE evidence_status = '未检索' OR {col} IS NOT NULL GROUP BY bucket ORDER BY bucket""").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["hits"] = d["hits"] or 0
            d["hit_rate"] = d["hits"] / d["n"] if d["n"] else None
            d["enough"] = d["n"] >= 30                    # §6.1：每桶 ≥ 30 条才看
            out.append(d)
        return out
