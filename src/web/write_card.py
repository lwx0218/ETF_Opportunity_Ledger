"""把手动立卡表单收成存储层已经认识的卡片与证据。不放宽冻结，不接收客户端传来的冻结字段。"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta

from src.data.universe import in_panel, load
from src.ledger.store import FIXED_SOURCES, SCORING_RULE, read_sources_csv

MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CARD_ID = re.compile(r"T-[0-9]{4}-[0-9]{3,}")
STATES = ("POP", "XB", "BNB", "REV", "EXH", "DROP", "XBD", "BNBD", "TREND_UP", "TREND_DOWN", "NEUTRAL")
CREATE_KEYS = {
    "theme_id", "thesis", "evidence", "horizon_days", "target_excess_pct", "benchmark",
    "invalidation_price", "thesis_inval_source_id", "thesis_inval_deadline",
    "thesis_inval_statement", "planned_size_pct", "tracking_days", "scoring_rule",
    "supersedes", "void_reason",
}
EVIDENCE_KEYS = {"source_id", "url", "title", "published_at", "summary"}


class FormError(ValueError):
    pass


def panel_containers(path=None):
    out = []
    for row in load() if path is None else load(path):
        if in_panel(row) and row.get("execution_fund_code"):
            out.append({"theme_id": row["theme_id"], "container": row["theme"],
                        "code": row["execution_fund_code"], "name": row["execution_fund_name"],
                        "research_index_code": row.get("research_index_code") or None})
    return out


def source_grades(path=None):
    _, rows = read_sources_csv(path or FIXED_SOURCES)
    return rows


def active_sources(path=None):
    return [{"source_id": sid, "name": name or sid, "grade": grade}
            for sid, (grade, name) in sorted(source_grades(path).items()) if grade in ("A", "B")]


def snapshot_sha256(url: str, excerpt: str) -> str:
    return hashlib.sha256((url + excerpt).encode("utf-8")).hexdigest()


def available_at(grade: str, published_at: str, first_seen: str) -> str:
    """A 级用数据源原样的分钟时刻；B 级取发布日次日 00:00 与首次看到时刻的较早者。"""
    if grade == "A":
        if not MINUTE.fullmatch(published_at or ""):
            raise FormError("A 级来源的发布时间须到分钟（YYYY-MM-DDTHH:MM），按数据源原样填写")
        return published_at
    if grade != "B":
        raise FormError("证据来源必须是固定源清单里的 A 或 B 级")
    if MINUTE.fullmatch(published_at or ""):
        day = published_at[:10]
    elif DAY.fullmatch(published_at or ""):
        day = published_at
    else:
        raise FormError("B 级来源的发布时间须为日期或到分钟")
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat() + "T00:00"
    return min(nxt, first_seen)


def _num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormError(f"{name}须为数字")
    number = float(value)
    if number != number or abs(number) >= 1e15:
        raise FormError(f"{name}不是有限数字")
    return number


def evidence_rows(items, grades, now):
    if not isinstance(items, list) or not items:
        raise FormError("至少一条证据")
    out = []
    for item in items:
        if not isinstance(item, dict) or set(item) - EVIDENCE_KEYS:
            raise FormError("证据含不允许的字段")
        grade = grades.get(item.get("source_id"), ("", None))[0]
        url, excerpt, title = item.get("url"), item.get("summary"), item.get("title") or ""
        published = item.get("published_at")
        if not isinstance(url, str) or not url.strip() or len(url) > 2000:
            raise FormError("证据须填写 URL")
        if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 4000:
            raise FormError("证据须填写摘录原文")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise FormError("证据须填写标题")
        if not isinstance(published, str):
            raise FormError("证据须填写发布时间")
        avail = available_at(grade, published, now)
        if avail < published or avail > now:
            raise FormError("这条证据的可用时点不在发布与当前时刻之间，当前还不能使用")
        digest = snapshot_sha256(url.strip(), excerpt.strip())
        out.append({"source_id": item["source_id"], "published_at": published,
                    "summary": f"{title.strip()}\n{excerpt.strip()}", "url": url.strip(),
                    "first_seen_at": now, "available_at": avail,
                    "snapshot_path": f"manual/{digest[:16]}", "snapshot_sha256": digest})
    return out


def assemble(body, *, quote, now, deadline, ew_level, hs300, instrument, grades):
    if not isinstance(body, dict) or set(body) - CREATE_KEYS:
        raise FormError("请求含不允许的字段；冻结字段不可修改")
    if body.get("theme_id") != instrument["theme_id"]:
        raise FormError("未知容器")
    thesis = body.get("thesis")
    if not isinstance(thesis, str) or not 1 <= len(thesis.strip()) <= 80:
        raise FormError("论点须为 1–80 字")
    horizon = body.get("horizon_days")
    if type(horizon) is not int or horizon <= 0:
        raise FormError("期限须为正整数个交易日")
    target = _num(body.get("target_excess_pct"), "超额目标")
    benchmark = body.get("benchmark")
    if benchmark not in ("等权组合", "沪深300"):
        raise FormError("基准只能是等权组合或沪深300")
    stop = _num(body.get("invalidation_price"), "价格失效位")
    close, atr = quote["close"], quote["atr20"]
    if stop <= 0 or stop >= close:
        raise FormError("价格失效位须大于 0 且低于最近收盘")
    state = quote.get("state")
    if state not in STATES:
        raise FormError("该容器执行 ETF 的形态不可用，不能立卡")
    source = body.get("thesis_inval_source_id")
    if grades.get(source, ("", None))[0] not in ("A", "B"):
        raise FormError("论点失效来源必须是固定源清单里的 A 或 B 级")
    inval_day = body.get("thesis_inval_deadline")
    if not isinstance(inval_day, str) or not DAY.fullmatch(inval_day):
        raise FormError("论点失效截止须为 YYYY-MM-DD")
    statement = body.get("thesis_inval_statement")
    if not isinstance(statement, str) or not statement.strip() or len(statement) > 500:
        raise FormError("请填写论点失效条件")
    size = _num(body.get("planned_size_pct"), "计划仓位")
    if not 0 < size <= 25:
        raise FormError("计划仓位须大于 0 且不超过 25%")
    if body.get("tracking_days", 20) != 20:
        raise FormError("跟踪天数固定为 20")
    if body.get("scoring_rule", SCORING_RULE) != SCORING_RULE:
        raise FormError("事件卡的评分规则只能是 schema-v1-§3")
    supersedes = body.get("supersedes")
    if supersedes is not None and (not isinstance(supersedes, str) or not CARD_ID.fullmatch(supersedes)):
        raise FormError("作废重建须指向一张已有卡片")
    if supersedes and (not isinstance(body.get("void_reason"), str) or not str(body.get("void_reason")).strip()):
        raise FormError("作废重建须填写作废理由")
    rank = quote.get("rank")
    if rank is not None:
        rank = int(rank)
    card = dict(
        created_at=now, close_date=quote["close_date"], scan_key=None, container=instrument["container"],
        instrument_code=instrument["code"], instrument_name=instrument["name"],
        research_index_code=instrument["research_index_code"], trigger_type="事件驱动", state_at_entry=state,
        thesis=thesis.strip(), evidence_status="有证据", expectation_horizon_days=horizon,
        expectation_target_excess_pct=target, expectation_benchmark=benchmark,
        invalidation_price=round(stop, 6), invalidation_atr_value=round(float(atr), 6),
        invalidation_atr_multiple=2.0, r_unit_per_share=round(close - stop, 6), r_unit_pct_of_nav=0.5,
        planned_size_pct=round(size, 6), scoring_rule=SCORING_RULE, tracking_days=20,
        cf_ew_level=ew_level, cf_hs300_level=hs300, cf_container_price=round(close, 6),
        crowd_rs_1m_rank=rank, thesis_inval_source_id=source, thesis_inval_deadline=inval_day,
        thesis_inval_statement=statement.strip(), owner_score_deadline=deadline, supersedes=supersedes,
    )
    return card, evidence_rows(body.get("evidence"), grades, now)
