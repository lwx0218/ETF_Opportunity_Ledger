"""候选卡触发规则（可插拔）。V1 结论出来之前只接「恐慌下轨」与「事件驱动」两类（replan §3 P5、A7）；
「形态突破」要等 V1 五条验收通过后再接（A7），这里不实现。

每条规则产出 Candidate；卡片的量化预期（horizon / target / benchmark）prereg 没有写死，
必须由规则配置文件给出（config/ledger-rules.example.json），缺了该规则就不启用——代码不自补参数。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ACTIVE_BEFORE_V1 = ("恐慌下轨", "事件驱动")
TERMS_VERSION = "jobs-daily-v0"        # docs/jobs-daily.md「骨架口径」的版本；配置里显式确认后规则才启用


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
    agent_score: dict | None = None        # 事件卡由起草人给；机械卡由 scorer 给
    thesis_invalidation: dict | None = None
    key_suffix: str = ""                   # 同日同容器多条事件时区分 scan_key


def load_rule_config(path: Path) -> dict:
    """{"confirmed_terms": TERMS_VERSION, "恐慌下轨": {"horizon_days": int, "target_excess_pct": float, "benchmark": "等权组合"|"沪深300"}, …}
    confirmed_terms 必须等于当前骨架口径版本（Cowork 复核过 docs/jobs-daily.md 的口径后填），否则一条规则都不启用。"""
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    if cfg.get("confirmed_terms") != TERMS_VERSION:
        return out
    for name in ACTIVE_BEFORE_V1:
        c = cfg.get(name) or {}
        if all(c.get(k) is not None for k in ("horizon_days", "target_excess_pct", "benchmark")):
            out[name] = {"horizon_days": int(c["horizon_days"]), "target_excess_pct": float(c["target_excess_pct"]),
                         "benchmark": c["benchmark"]}
    return out


def panic_candidates(day_rows: pd.DataFrame, z_threshold: float) -> list[Candidate]:
    """prereg-v1 §3.2：月末 z ≤ −2（z_month 只在月末行有值）；越超跌越优先。"""
    rows = day_rows[day_rows["z_month"].le(z_threshold) & day_rows["atr20"].gt(0)]
    return [Candidate(container=r.container, trigger_type="恐慌下轨", state=r.state, close=float(r.close), atr20=float(r.atr20),
                      z=float(r.z_month), priority=float(r.z_month),
                      thesis=f"月末 z={r.z_month:.2f} ≤ {z_threshold:g}，恐慌下轨（prereg-v1 §3.2）")
            for r in rows.itertuples(index=False)]


def event_candidates(day_rows: pd.DataFrame, events_dir: Path | None, day: str) -> tuple[list[Candidate], list[str]]:
    """事件卡由人确认后的草稿文件 <events_dir>/<day>.json 进来（schema §7：起卡需要一次确认）。
    每条：{container, thesis, evidence[], agent_score{score, reason}, thesis_invalidation{source_id, deadline, statement}}。"""
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
        why = ("当日无该容器的收盘或 ATR20" if r is None or not (r.atr20 > 0)
               else "论点为空或超过 80 字（不截断，退回重写）" if not thesis or len(thesis) > 80
               else "缺论点失效条件（A3：source_id / deadline / statement）" if not all(ti.get(k) for k in ("source_id", "deadline", "statement"))
               else "缺 agent 评分与理由（A1）" if score.get("score") is None or not score.get("reason") else None)
        if why:
            problems.append(f"{tag}：{why}，未立卡")
            continue
        out.append(Candidate(container=r.container, trigger_type="事件驱动", state=r.state, close=float(r.close),
                             atr20=float(r.atr20), thesis=thesis, priority=1e6 + i, evidence=e.get("evidence") or [],
                             agent_score=score, thesis_invalidation=ti, key_suffix=f"|{i}"))
    return out, problems
