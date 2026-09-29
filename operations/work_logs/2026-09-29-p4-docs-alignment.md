# P4 · 文档对齐（A6）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §3 P4——把已批准的 A1–A7 / C 与 A6 的权威位置落到文档与 AGENTS.md
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Executor: Claude Code（云端）
- Route: direct-execute（Owner 指示：改 AGENTS.md 的这一包单独一个 PR）
- Source of truth: `operations/planning/2026-09-27-astra-execution.md`「已确认的决定」；replan §3 P4

## 结果

| 改动 | 位置 |
|---|---|
| A1–A7、C 的「决定」栏按 astra-execution 的记录转录，注明转录人与日期 | `operations/planning/2026-09-27-orchestration-input.md` |
| §4.1「权威版本在 claude.ai Project」→「权威版本在仓库 `docs/`，Project 为只读快照」；初始化边界段后加 09-29 状态注（原段保留） | `docs/project-intake/etf-opportunity-ledger.md` |
| PROJECT:OWNED 三句改为当前状态：已导入 / 任务 0 收口、1–6 按 replan 推进、7 延后 / §10 五项已由 A1–A5 决定 | `AGENTS.md` |
| §8 加一行指向 `docs/etf-fixed-sources-v1.md` | `docs/etf-rotation-framework-v0.md` |

**超出 replan 列举的一处**：AGENTS.md「设计资产待导入」同为过时状态（`docs/design/` 已有 design-rules v3 与 tokens.css），一并改为「已导入」。Harness 管理分区未动。

## 未改

- card schema、prereg、fixed-sources 正文不改；A1 双栏与证据时点字段的 schema v1.1 由 Cowork 另写。
- AGENTS.md「任务顺序遵循 intake §7」一句未改：replan 的分线并行仍保持 intake §7 的依赖顺序。
