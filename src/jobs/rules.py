"""候选卡触发规则（可插拔）。V1 结论出来之前只接「恐慌下轨」与「事件驱动」两类（replan §3 P5、A7）；
「形态突破」要等 V1 五条验收通过后再接（A7），这里不实现。

每条规则产出 Candidate。规则卡（恐慌下轨）按 schema v1.1-c 用评分菜单第 2 项（R 倍数：horizon 为空、+2R、基准等权），
evidence_status = 未检索、不写 agent 分（v1.1-a）；事件卡用菜单第 1 项，horizon / target / benchmark 与检索状态由起草人逐卡填。
规则配置 config/ledger-rules.json：confirmed_terms 须等于 TERMS_VERSION，且该规则 enabled 为真才启用（V1 结论前全部关闭，A7）。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ACTIVE_BEFORE_V1 = ("恐慌下轨", "事件驱动")
TERMS_VERSION = "jobs-daily-v5"        # docs/jobs-daily.md 口径版本（v1：v1.1-e；v2：v1.1-f 证伪判定；v3：v1.1-g 出场信号持久化；
                                       # v4：v1.1-h 出场信号边角 + I-26 断档行不做决策；v5：v1.1-i 信号时限、出场在断档顺延、
                                       # 事件与排名不用断档行）；配置里显式确认后规则才启用
RULE_R = {"scoring_rule": "schema-v1.1-R", "horizon_days": None, "target_excess_pct": None, "target_r": 2, "benchmark": "等权组合"}


@dataclass
class Candidate:
    container: str
    trigger_type: str
    state: str
    close: float
    atr20: float
    thesis: str
    priority: float                        # 同日多个候选抢空位时的顺序（小者先）；I-07
    z: float | None = None
    evidence: list[dict] = field(default_factory=list)
    agent_score: dict | None = None        # 事件卡由起草人给；机械卡不写（v1.1-a）
    thesis_invalidation: dict | None = None
    key_suffix: str = ""                   # 同日同容器多条事件时区分 scan_key
    evidence_status: str = "未检索"         # v1.1-a：机械卡 = 未检索；事件卡 = 已检索无证据 / 有证据
    expectation: dict | None = None        # 事件卡的逐卡预期 {horizon_days, target_excess_pct, benchmark}


def load_rule_config(path: Path, problems: list[str] | None = None) -> dict:
    """返回启用的规则 → 卡片预期：
    {"confirmed_terms": "jobs-daily-v5",
     "恐慌下轨": {"enabled": true, "scoring_rule": "schema-v1.1-R", "horizon_days": null, "target_r": 2, "benchmark": "等权组合"},
     "事件驱动": {"enabled": true}}                                  # 事件卡的预期由草稿逐卡给
    confirmed_terms 不等于当前口径版本、或 enabled 不为真的规则不启用；恐慌规则的预期必须是菜单第 2 项（v1.1-c）。
    请求启用（enabled 为 true）却被拒的原因追加进 problems，由调用方报告，不静默关掉。"""
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = problems if problems is not None else []
    out = {}
    wanted = [k for k in ACTIVE_BEFORE_V1 if (cfg.get(k) or {}).get("enabled") is True]
    if cfg.get("confirmed_terms") != TERMS_VERSION:
        if wanted:
            problems.append(f"{'、'.join(wanted)} 请求启用，但 confirmed_terms 不是 {TERMS_VERSION}：全部不启用")
        return out
    panic = cfg.get("恐慌下轨") or {}
    if panic.get("enabled") is True:
        if all(panic.get(k) == v for k, v in RULE_R.items()):
            out["恐慌下轨"] = dict(RULE_R)
        else:
            problems.append(f"恐慌下轨请求启用，但预期不是评分菜单第 2 项 {RULE_R}：不启用")
    if (cfg.get("事件驱动") or {}).get("enabled") is True:
        out["事件驱动"] = {}
    return out


def _number(x, integer: bool) -> bool:
    """起草人写的数：不接受字符串、布尔、非有限值；整数项不接受小数（不替起草人取整）。"""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return False
    return isinstance(x, int) or not integer


def panic_candidates(day_rows: pd.DataFrame, z_threshold: float) -> list[Candidate]:
    """prereg-v1 §3.2：月末 z ≤ −2（z_month 只在月末行有值）；越超跌越优先。断档行（data_hole = 1）不看（I-26）。"""
    rows = day_rows[day_rows["z_month"].le(z_threshold) & day_rows["atr20"].gt(0) & day_rows["data_hole"].eq(0)]
    return [Candidate(container=r.container, trigger_type="恐慌下轨", state=r.state, close=float(r.close), atr20=float(r.atr20),
                      z=float(r.z_month), priority=float(r.z_month),
                      thesis=f"月末 z={r.z_month:.2f} ≤ {z_threshold:g}，恐慌下轨（prereg-v1 §3.2）")
            for r in rows.itertuples(index=False)]


def event_candidates(day_rows: pd.DataFrame, events_dir: Path | None, day: str) -> tuple[list[Candidate], list[str]]:
    """事件卡由人确认后的草稿文件 <events_dir>/<day>.json 进来（schema §7：起卡需要一次确认）。每条：
    {container, thesis, evidence_status（已检索无证据 / 有证据）, evidence[], agent_score{score, reason},
     expectation{horizon_days, target_excess_pct, benchmark}, thesis_invalidation{source_id, deadline, statement}}。"""
    if not events_dir:
        return [], []
    f = Path(events_dir) / f"{day}.json"
    if not f.exists():
        return [], []
    by = {r.container: r for r in day_rows.itertuples(index=False)}
    out, problems = [], []
    try:
        drafts = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as err:
        return [], [f"事件草稿文件 {f.name} 不是合法 JSON（{err}），当天不立事件卡"]
    if not isinstance(drafts, list):
        return [], [f"事件草稿文件 {f.name} 应是草稿列表，当天不立事件卡"]
    for i, e in enumerate(drafts):
        if not isinstance(e, dict):
            problems.append(f"事件草稿 {i}：不是对象，未立卡")
            continue
        tag = f"事件草稿 {i}（{e.get('container')}）"
        r = by.get(e.get("container"))
        thesis = e.get("thesis").strip() if isinstance(e.get("thesis"), str) else ""
        ti, score, exp = (x if isinstance(x, dict) else {} for x in (e.get("thesis_invalidation"), e.get("agent_score"), e.get("expectation")))
        status, evidence = e.get("evidence_status"), e.get("evidence") or []
        why = ("当日无该容器的收盘或 ATR20" if r is None or not (r.atr20 > 0)
               else "该容器当日数据断档（data_hole = 1，收盘与 ATR 是陈旧拷贝；v1.1-i 第 4 条）" if r.data_hole != 0
               else "论点为空或超过 80 字（不截断，退回重写）" if not thesis or len(thesis) > 80
               else "缺论点失效条件（A3：source_id / deadline / statement）" if not all(ti.get(k) for k in ("source_id", "deadline", "statement"))
               else "缺 agent 评分与理由（A1）" if score.get("score") is None or not score.get("reason")
               else "evidence 须为列表" if not isinstance(evidence, list)
               else "evidence_status 须为「已检索无证据」或「有证据」，且与证据条数一致（v1.1-a）"
               if not ((status == "已检索无证据" and not evidence) or (status == "有证据" and evidence))
               else "缺逐卡预期或格式不对（horizon_days 为正整数、target_excess_pct 为数、benchmark ∈ 等权组合 / 沪深300，菜单第 1 项）"
               if not (_number(exp.get("horizon_days"), True) and exp["horizon_days"] > 0 and _number(exp.get("target_excess_pct"), False)
                       and exp.get("benchmark") in ("等权组合", "沪深300"))
               else None)
        if why:
            problems.append(f"{tag}：{why}，未立卡")
            continue
        out.append(Candidate(container=r.container, trigger_type="事件驱动", state=r.state, close=float(r.close),
                             atr20=float(r.atr20), thesis=thesis, priority=1e6 + i, evidence=evidence,
                             agent_score=score, thesis_invalidation=ti, key_suffix=f"|{i}", evidence_status=status,
                             expectation={"scoring_rule": "schema-v1-§3", "horizon_days": exp["horizon_days"],
                                          "target_excess_pct": exp["target_excess_pct"], "target_r": None,
                                          "benchmark": exp["benchmark"]}))
    return out, problems
