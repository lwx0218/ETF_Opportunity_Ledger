"""已定口径的审查提醒与冻结对照值；不替 Owner 作审查决定。

口径：card schema §6、ledger-storage「统计口径」。Agent 分桶不进入 Owner 报告，
包括已作废但仍可独立评分的卡；独立复核另行读取，避免终态过滤仍泄露双盲分数。
"""
from __future__ import annotations

from math import fsum
import sqlite3

from src.ledger import read


def review_report(con: sqlite3.Connection) -> dict:
    """只查询现有台账。连接需 sqlite3.Row；不建表、不推导未裁定的季度或年度口径。"""
    owner = read.calibration(con, "owner")
    unscored = dict(con.execute("""SELECT count(*) AS total,
        coalesce(sum(status IN ('已结','作废')),0) AS n,
        coalesce(sum(status NOT IN ('已结','作废')),0) AS open
        FROM card_status WHERE evidence_status <> '未检索' AND owner_strength IS NULL""").fetchone())
    for bucket in owner:
        bucket["interpretation"] = ("仅列事实，审查结论由独立复核给出" if bucket["enough"]
                                    else "样本不足，不下结论")
    closed = [dict(r) for r in con.execute("""
        SELECT c.id AS card_id, f.recorded_at AS finalized_at, x.realized_r
          FROM cards c JOIN finals f ON f.card_id = c.id JOIN exits x ON x.card_id = c.id
         WHERE c.sealed = 1
         ORDER BY f.recorded_at DESC, c.id DESC LIMIT 20""")]
    mean_r = fsum(r["realized_r"] for r in closed) / 20 if len(closed) == 20 else None
    total, manual = con.execute("SELECT count(*), coalesce(sum(exit_reason = '手动'), 0) FROM exits").fetchone()
    share = manual / total if total else None
    alerts = [
        {"id": "last_20_mean_r", "title": "连续 20 张已结卡片的平均 R", "n": len(closed),
         "required_n": 20, "value": mean_r, "threshold": -0.2, "operator": "<=",
         "triggered": None if mean_r is None else mean_r <= -0.2, "facts": closed},
        {"id": "manual_exit_share", "title": "手动出场占已出场比例", "n": total,
         "required_n": 1, "value": share, "threshold": 0.3, "operator": ">",
         "triggered": None if share is None else share > 0.3,
         "facts": {"manual_count": manual, "exited_count": total}},
    ]
    for alert in alerts:
        alert["status"] = ("insufficient" if alert["triggered"] is None else
                           "triggered" if alert["triggered"] else "clear")
    return {
        "calibration": {
            "owner": owner,
            "unscored": unscored,
            "agent": {"status": "held_until_review", "reason": "Owner 入口不披露 agent 个体评分或分桶，避免双盲信息泄露。"},
        },
        "alerts": alerts,
        "pending": [
            {"id": "random_container", "title": "随机容器反事实", "status": "pending",
             "reason": "尚未冻结抽样池、抽样时点、随机规则和比较窗口；不能事后选择容器。"},
            {"id": "quarterly_reversal", "title": "连续三个季度校准反向", "status": "pending",
             "reason": "季度比较指标和每季样本不足的处理待裁定，不自动判断反向。"},
            {"id": "annual_review", "title": "每 12 个月全面审查", "status": "pending",
             "reason": "首次起算日及上次正式审查记录未建立，不自动推定到期日。"},
            {"id": "universe_change", "title": "容器池结构变化", "status": "pending",
             "reason": "缺少带时点的清盘、新主题及成交额前十证据；当前容器清单不足以判定变化。"},
        ],
        "allowed_decisions": ["继续", "停止", "重开新版本"],
        "automatic_actions": False,
    }


def counterfactual(con: sqlite3.Connection, card_id: str) -> dict | None:
    """呈现冻结点位和已入账的锁定基准超额，不用不完整端点重算收益。

DailyJob 的 daily.bench_close 通常写沪深300，但存储层没有逐点来源与开盘窗口标识；
它不能独立证明与冻结点位同源，亦不能替代真实成交窗口端点。本读模型不拼接比较。
"""
    card = con.execute("""SELECT close_date, cf_ew_level, cf_hs300_level, cf_container_price,
                                 expectation_benchmark FROM cards WHERE id = ? AND sealed = 1""", (card_id,)).fetchone()
    if card is None:
        return None
    result = con.execute("""SELECT e.entry_date, x.exit_date, x.realized_excess_pct, x.realized_r
                              FROM entries e JOIN exits x ON x.card_id = e.card_id
                             WHERE e.card_id = ?""", (card_id,)).fetchone()
    return {
        "frozen": {"date": card["close_date"], "equal_weight_level": card["cf_ew_level"],
                   "hs300_level": card["cf_hs300_level"], "container_price": card["cf_container_price"]},
        "recorded_result": ({"benchmark": card["expectation_benchmark"], **dict(result)} if result else None),
        "comparisons": [
            {"id": "equal_weight", "status": "pending",
             "reason": "仅展示冻结等权点位；尚未完整核对同期端点与持有窗口，不另算对照收益。"},
            {"id": "hs300", "status": "pending",
             "reason": "仅展示冻结沪深300点位；缺逐点来源与成交窗口证明，不能据每日基准观测拼算收益。"},
            {"id": "random_container", "status": "pending",
             "reason": "随机容器身份和选择口径尚未事前冻结，不补选。"},
        ],
    }
