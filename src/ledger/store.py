"""卡片台账的 SQLite 存储。纪律在存储层（schema.sql 的 CHECK 与触发器）强制，这里只是薄封装：
Python 层的校验只为给出可读的错误，绕过它直接写 SQL 同样会被拒绝。

冻结 = cards / evidence / strength_scores / entries / daily / exits / finals / voids 全部拒绝 DELETE；
除 cards 在创建事务里把 sealed 从 0 置 1 之外，全部拒绝 UPDATE。
注意：拿到数据库文件的人仍可 DROP TRIGGER——存储层能防误改和流程绕行，防不了蓄意篡改；文件应只由台账进程写入。
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = Path(__file__).with_name("schema.sql")
FIXED_SOURCES = ROOT / "docs" / "etf-fixed-sources-v1.csv"
DEFAULT_DB = ROOT / "data" / "ledger.sqlite"          # 不入 Git（.gitignore：*.sqlite）

APPEND_ONLY = ("cards", "evidence", "strength_scores", "entries", "daily", "exits", "finals", "voids")
CARD_FIELDS = (
    "id", "created_at", "close_date", "container", "instrument_code", "instrument_name", "research_index_code",
    "trigger_type", "state_at_entry", "thesis", "expectation_horizon_days", "expectation_target_excess_pct",
    "expectation_benchmark", "invalidation_price", "invalidation_atr_value", "invalidation_atr_multiple",
    "r_unit_per_share", "r_unit_pct_of_nav", "planned_size_pct", "scoring_rule", "tracking_days",
    "cf_ew_level", "cf_hs300_level", "cf_container_price", "crowd_rs_1m_rank", "crowd_rs_3m_rank",
    "crowd_vol_ratio_20", "crowd_premium_pct", "crowd_share_chg_20d", "thesis_inval_source_id",
    "thesis_inval_deadline", "thesis_inval_statement", "owner_score_deadline", "supersedes",
)
EVIDENCE_FIELDS = ("source_id", "published_at", "summary", "url", "first_seen_at", "available_at", "snapshot_path", "snapshot_sha256")
SCORING_RULE = "schema-v1-§3"


class LedgerError(ValueError):
    """存储层拒绝了一次写入（触发器 / 约束），原因写在消息里。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _freeze_triggers() -> str:
    others = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in CARD_FIELDS)
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


def mechanical_score(exit_reason: str, realized_excess_pct: float, target_excess_pct: float) -> str:
    """schema §3 四档，与 finals 触发器同一口径。"""
    if exit_reason == "失效位":
        return "证伪"
    if realized_excess_pct >= target_excess_pct:
        return "达标"
    return "部分" if realized_excess_pct > 0 else "未达"


class Ledger:
    def __init__(self, path: Path | str = DEFAULT_DB, sources: Path = FIXED_SOURCES):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None)      # 事务由 _tx 显式控制
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA.read_text(encoding="utf-8") + "\n" + _freeze_triggers())
        self.load_sources(sources)

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------ 基础
    def _tx(self, fn):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            out = fn()
        except sqlite3.DatabaseError as e:
            self.conn.execute("ROLLBACK")
            raise LedgerError(str(e)) from e
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")
        return out

    def _insert(self, table: str, row: dict):
        cols = list(row)
        self.conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [row[c] for c in cols])

    def load_sources(self, path: Path = FIXED_SOURCES) -> int:
        """把固定源清单同步进库（等级会随 S2 核实变化；已写入卡片的证据不受影响）。"""
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [(r["source_id"].strip(), r.get("名称"), r["等级"].strip(), _now()) for r in csv.DictReader(f)]
        self._tx(lambda: self.conn.executemany(
            "INSERT INTO fixed_sources (source_id, name, grade, loaded_at) VALUES (?,?,?,?) "
            "ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, grade=excluded.grade, loaded_at=excluded.loaded_at", rows))
        return len(rows)

    def next_id(self, year: int) -> str:
        n = self.conn.execute("SELECT count(*) FROM cards WHERE id GLOB ?", (f"T-{year}-*",)).fetchone()[0]
        return f"T-{year}-{n + 1:03d}"

    # ------------------------------------------------------------ 生命周期
    def create_card(self, card: dict, evidence: list[dict], agent_score: dict) -> str:
        """一次事务：卡片（未封存）→ 证据 → agent 评分 → 封存。任何一步被拒，整张卡不入库。
        evidence 可以是空列表：表示当时固定源上没有证据，这也是合法记录。"""
        unknown = set(card) - set(CARD_FIELDS)
        if unknown:
            raise LedgerError(f"未知字段：{sorted(unknown)}")
        card = {"scoring_rule": SCORING_RULE, "tracking_days": 20, **card}

        def run():
            if "id" not in card:
                card["id"] = self.next_id(int(card["created_at"][:4]))
            self._insert("cards", card)
            for i, ev in enumerate(evidence, 1):
                extra = set(ev) - set(EVIDENCE_FIELDS)
                if extra:
                    raise LedgerError(f"证据未知字段：{sorted(extra)}")
                self._insert("evidence", {"card_id": card["id"], "seq": i, **ev})
            self._insert("strength_scores", {"card_id": card["id"], "rater": "agent", **agent_score})
            self.conn.execute("UPDATE cards SET sealed = 1 WHERE id = ?", (card["id"],))
            return card["id"]
        return self._tx(run)

    def owner_score(self, card_id: str, score: int, reason: str, scored_at: str) -> None:
        self._tx(lambda: self._insert("strength_scores", {"card_id": card_id, "rater": "owner", "score": score,
                                                          "reason": reason, "scored_at": scored_at}))

    def enter(self, card_id: str, entry_date: str, entry_price: float, size_pct: float) -> None:
        self._tx(lambda: self._insert("entries", {"card_id": card_id, "entry_date": entry_date, "entry_price": entry_price,
                                                  "size_pct": size_pct, "recorded_at": _now()}))

    def append_daily(self, card_id: str, row: dict) -> None:
        self._tx(lambda: self._insert("daily", {"card_id": card_id, **row}))

    def exit(self, card_id: str, **row) -> None:
        self._tx(lambda: self._insert("exits", {"card_id": card_id, "recorded_at": _now(), **row}))

    def finalize(self, card_id: str, **row) -> None:
        self._tx(lambda: self._insert("finals", {"card_id": card_id, "recorded_at": _now(), **row}))

    def void(self, card_id: str, reason: str, voided_at: str) -> None:
        self._tx(lambda: self._insert("voids", {"card_id": card_id, "reason": reason, "voided_at": voided_at}))

    # ------------------------------------------------------------ 读
    def card(self, card_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return dict(r) if r else None

    def evidence(self, card_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM evidence WHERE card_id = ? ORDER BY seq", (card_id,))]

    def status(self, card_id: str) -> str | None:
        r = self.conn.execute("SELECT status FROM card_status WHERE id = ?", (card_id,)).fetchone()
        return r[0] if r else None

    def summary(self) -> dict:
        """分母 = 全部卡片（含作废、含未进场）。只统计进场或已结的卡等于用结果筛样本（schema §1）。"""
        q = lambda s, *a: self.conn.execute(s, a).fetchall()   # noqa: E731
        total = q("SELECT count(*) FROM card_status")[0][0]
        by_status = {r[0]: r[1] for r in q("SELECT status, count(*) FROM card_status GROUP BY status")}
        by_score = {r[0]: r[1] for r in q("SELECT final_score, count(*) FROM card_status WHERE final_score IS NOT NULL GROUP BY final_score")}
        exits = q("SELECT count(*), sum(exit_reason = '手动') FROM exits")[0]
        return {
            "denominator": total, "by_status": by_status, "by_final_score": by_score,
            "hit_rate_over_all_cards": (by_score.get("达标", 0) / total) if total else None,
            "manual_exit_share": (exits[1] / exits[0]) if exits[0] else None,        # §6.4 触发器之一：> 30%
            "superseded": q("SELECT count(*) FROM cards WHERE supersedes IS NOT NULL")[0][0],
        }

    def calibration(self, rater: str = "agent") -> list[dict]:
        """schema §6.1：按事前 evidence_strength 分桶（0–1 / 2–3 / 4–5）。n 含作废与未结卡；达标率以 n 为分母。"""
        col = {"agent": "agent_strength", "owner": "owner_strength"}[rater]
        rows = self.conn.execute(f"""
            SELECT CASE WHEN {col} <= 1 THEN '0–1' WHEN {col} <= 3 THEN '2–3' ELSE '4–5' END AS bucket,
                   count(*) AS n, sum(status = '作废') AS voided, sum(status = '已结') AS closed,
                   sum(final_score = '达标') AS hits, avg(CASE WHEN status = '已结' THEN realized_r END) AS mean_r_closed
              FROM card_status WHERE {col} IS NOT NULL GROUP BY bucket ORDER BY bucket""").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["hit_rate"] = (d["hits"] or 0) / d["n"]
            d["enough"] = d["n"] >= 30                    # §6.1：每桶 ≥ 30 条才看
            out.append(d)
        return out
