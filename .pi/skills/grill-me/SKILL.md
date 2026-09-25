---
name: grill-me
description: Sharpen a fuzzy plan or design when no stable repository/document baseline exists. Use for bounded blocking-decision interviews before implementation, especially when the user asks to be grilled.
---

# Grill Me

Use when the request is still fuzzy and no stable Plan/spec/evidence baseline exists. Do not use when repository documents already provide the decisions; use `grill-with-docs` instead.

## Interview Contract

- default maximum 3 discovery rounds
- group 3–5 related blocking decisions per round
- target maximum 12–15 blocking decisions total
- provide a recommended default for every decision
- allow `accept recommended defaults`; this resolves discovery decisions but never approves a durable Plan
- ask only when the answer changes scope/acceptance, architecture/data ownership, or a hard-to-reverse/high-risk choice
- infer anything available from the repository rather than asking
- assume or defer non-blocking detail
- if blockers remain at budget exhaustion, ask for explicit Owner opt-in to `deep-discovery`; otherwise stop

End each response with:

- Resolved
- Assumed
- Blocking
- Deferred
- Question budget remaining

## Desired Outcome

- settled goal and source of truth
- blocking scope/architecture/acceptance decisions resolved
- explicit assumptions and backlog
- recommended route: `direct-execute`, `plan`, - clear validation and next human control gate

## Greenfield No-Write Boundary

If this runs inside `00-orchestration` before Plan approval, keep all candidate decisions and Plan Preview in chat. Do not modify code/config or create Plan, `CONTEXT.md`, ADR, work log, or other project artifacts.

## Boundaries

- do not interrogate every branch merely because it exists
- do not ask one endless question at a time
- do not implement during grilling
- do not write durable evidence before the applicable confirmation gate
- do not force domain modeling, subagents, MCP, or packages without a real trigger

## 何时用哪个

- **grill-me**（本 skill）：没有稳定基线时，从零做有界澄清访谈。
- **grill-with-docs**：已有实质决策基线时，对照仓库证据做压力测试。

两者共享同一套 interview contract（3 轮 / 每轮 3–5 个 blocking decision / 总量 12–15 / 每题带 recommended default / 结尾给 Resolved-Assumed-Blocking-Deferred-剩余预算）。选不准时默认用本 skill。
