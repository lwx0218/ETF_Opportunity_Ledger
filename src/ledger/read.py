"""台账只读统计；连接由调用方提供，不建库、不迁移、不载入固定源。

连接需设置 sqlite3.Row。双盲界面的 agent 评分披露由调用方控制，不能直接公开在途分桶。
"""
from __future__ import annotations

import sqlite3


def summary(con: sqlite3.Connection) -> dict:
    """分母 = 全部卡片（含作废、含未进场、含仍在途的）。只统计进场或已结的卡等于用结果筛样本（schema §1）。"""
    q = lambda s, *a: con.execute(s, a).fetchall()   # noqa: E731
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


def calibration(con: sqlite3.Connection, rater: str = "agent") -> list[dict]:
    """schema §6.1 + v1.1-a：只用检索过的卡（已检索无证据 / 有证据）按事前 evidence_strength 分桶（0–1 / 2–3 / 4–5）；
    未检索的卡单独成一桶「未检索」，仍计入分母。n = 终态卡（已结 + 作废，作废计入分母）；达标率以 n 为分母；在途卡单列 open。"""
    col = {"agent": "agent_strength", "owner": "owner_strength"}[rater]
    rows = con.execute(f"""
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
