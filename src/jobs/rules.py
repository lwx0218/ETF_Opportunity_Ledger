"""候选卡触发规则（可插拔）。V1 结论出来之前只接「恐慌下轨」与「事件驱动」两类（replan §3 P5、A7）；
「形态突破」要等 V1 五条验收通过后再接（A7），这里不实现。

每条规则产出 Candidate。规则卡（恐慌下轨）按 schema v1.1-c 用评分菜单第 2 项（R 倍数：horizon 为空、+2R、基准等权），
evidence_status = 未检索、不写 agent 分（v1.1-a）；事件卡用菜单第 1 项，horizon / target / benchmark 与检索状态由起草人逐卡填。
规则配置 config/ledger-rules.json：confirmed_terms 须等于 TERMS_VERSION，且该规则 enabled 为真才启用（V1 结论前全部关闭，A7）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ACTIVE_BEFORE_V1 = ("恐慌下轨", "事件驱动")
TERMS_VERSION = "jobs-daily-v1"        # docs/jobs-daily.md 口径版本（schema v1.1-e 确认后升级）；配置里显式确认后规则才启用
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


def load_rule_config(path: Path) -> dict:
    """返回启用的规则 → 卡片预期：
    {"confirmed_terms": "jobs-daily-v1",
     "恐慌下轨": {"enabled": true, "scoring_rule": "schema-v1.1-R", "horizon_days": null, "target_r": 2, "benchmark": "等权组合"},
     "事件驱动": {"enabled": true}}                                  # 事件卡的预期由草稿逐卡给
    confirmed_terms 不等于当前口径版本、或 enabled 不为真的规则不启用；恐慌规则的预期必须是菜单第 2 项（v1.1-c）。"""
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    if cfg.get("confirmed_terms") != TERMS_VERSION:
        return out
    panic = cfg.get("恐慌下轨") or {}
    if panic.get("enabled") is True and all(panic.get(k) == v for k, v in RULE_R.items() if k not in ("horizon_days", "target_excess_pct")) \
            and panic.get("horizon_days") is None and panic.get("target_excess_pct") is None:
        out["恐慌下轨"] = dict(RULE_R)
    if (cfg.get("事件驱动") or {}).get("enabled") is True:
        out["事件驱动"] = {}
    return out


def panic_candidates(day_rows: pd.DataFrame, z_threshold: float) -> list[Candidate]:
    """prereg-v1 §3.2：月末 z ≤ −2（z_month 只在月末行有值）；越超跌越优先。"""
    rows = day_rows[day_rows["z_month"].le(z_threshold) & day_rows["atr20"].gt(0)]
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
    for i, e in enumerate(json.loads(f.read_text(encoding="utf-8"))):
        tag = f"事件草稿 {i}（{e.get('container')}）"
        r = by.get(e.get("container"))
        thesis = (e.get("thesis") or "").strip()
        ti, score = e.get("thesis_invalidation") or {}, e.get("agent_score") or {}
        exp, status, evidence = e.get("expectation") or {}, e.get("evidence_status"), e.get("evidence") or []
        why = ("当日无该容器的收盘或 ATR20" if r is None or not (r.atr20 > 0)
               else "论点为空或超过 80 字（不截断，退回重写）" if not thesis or len(thesis) > 80
               else "缺论点失效条件（A3：source_id / deadline / statement）" if not all(ti.get(k) for k in ("source_id", "deadline", "statement"))
               else "缺 agent 评分与理由（A1）" if score.get("score") is None or not score.get("reason")
               else "evidence_status 须为「已检索无证据」或「有证据」，且与证据条数一致（v1.1-a）"
               if not ((status == "已检索无证据" and not evidence) or (status == "有证据" and evidence))
               else "缺逐卡预期（horizon_days / target_excess_pct / benchmark，菜单第 1 项）"
               if exp.get("horizon_days") is None or exp.get("target_excess_pct") is None or exp.get("benchmark") not in ("等权组合", "沪深300")
               else None)
        if why:
            problems.append(f"{tag}：{why}，未立卡")
            continue
        out.append(Candidate(container=r.container, trigger_type="事件驱动", state=r.state, close=float(r.close),
                             atr20=float(r.atr20), thesis=thesis, priority=1e6 + i, evidence=evidence,
                             agent_score=score, thesis_invalidation=ti, key_suffix=f"|{i}", evidence_status=status,
                             expectation={"scoring_rule": "schema-v1-§3", "horizon_days": int(exp["horizon_days"]),
                                          "target_excess_pct": float(exp["target_excess_pct"]), "target_r": None,
                                          "benchmark": exp["benchmark"]}))
    return out, problems
