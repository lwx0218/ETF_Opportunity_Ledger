---
name: governance-loop-entry
description: Start or resume the minimal governance loop for this project — greenfield kickoff, bounded planning, round dispatch, closeout. Use when a task needs routing or durable governance evidence.
---

# Governance Loop Entry

## Purpose

`ETF_Opportunity-Ledger` 的治理入口。轻量起步，只在复杂度或缺少 baseline 时才展开。

## Read First

1. `AGENTS.md`
2. `Harness_manual.md`
3. `.pi/agents/README.md`
4. `.pi/prompt-templates/project-kickoff.md`
5. `.pi/prompt-templates/governance-loop.md`

## Applicability Gate

- **Greenfield 或无 approved baseline**：在 `00-orchestration` session 里走 project-kickoff 契约，Owner 明确确认规划前保持 planning-only。
- **已有稳定 baseline + 后续 bounded task**：走 `/governance-loop` 的 `Gate -> Route`。不要强行套 kickoff、Spec 或 Plan。

## Pre-Approval No-Write Boundary

Owner 确认规划前，可以 read / infer / discuss 并在聊天里展示 Plan Preview。

不得：修改业务代码或配置；创建或更新 Plan、intake、`CONTEXT.md`、ADR、work log；安装依赖或执行破坏性操作；开始实现或声称有开发进展。

bootstrap 生成的脚手架先于本次对话存在，不构成额外写入授权。

## Bounded Discovery Contract

需要用户决策时：

- 默认最多 3 轮，每轮 3–5 个相关 blocking decision，总量上限 12–15
- 每个决策带 recommended default；Owner 可回 `accept recommended defaults`
- 能从仓库推断的不要问
- 只在答案会改变范围/验收、架构/数据归属，或属于难以回退的高风险选择时才问
- 非阻塞不确定性记为 assumption 或 backlog

每次回复结尾给出：Resolved / Assumed / Blocking / Deferred / 剩余预算。

## Route

- `direct-execute`：清楚的 bounded task
- `plan`：需要澄清范围、风险、验证或切分 round
- `review-only`：只要 findings
- `needs-package`：确有能力缺口

## Optional Baseline Skills

- `grill-me`：route 不稳定或缺少稳定基线时的有界访谈
- `grill-with-docs`：已有实质基线时，对照仓库证据做压力测试
- `domain-modeling`：术语、实体、状态流转、归属或 bounded context 确实模糊时启用；确认前 no-write

## Plan Preview 与确认

终态三选一：`blocking-decisions` / `ready-for-approval` / `approved-and-persisted`。完整字段和固定结尾语见 `.pi/prompt-templates/project-kickoff.md`，本文不复述。

接受 recommended defaults 不等于批准规划。

## Round 分发

规划确认后，在 Orchestration session 里用 `/fleet` 为每个 round `session_spawn` 一个开发 session，round 间通过 `session_bus` 同步状态。

round 内按宿主选择 builder / reviewer 执行器：Web UI 内置工具可用时用 `subagent_spawn`，匹配角色模板优先 `delegate_task`；CLI 或无 Web UI 工具时用独立 `pi-subagents` 与 `.pi/agents/` 角色。不要求 Web UI 经 pi-subagents，不为兼容升级或 patch 包。只读是 reviewer 的角色约束，不是运行时沙箱承诺。

新增代码由 ponytail 门禁。**round 内的复核结论由 reviewer 给出，不要推回 Owner。**

round 是任务切分单位，不是验收单位：说清目标、改动面、验证方式、完成判据即可，不需要 ledger 或跨 round 状态机。

## Durable Evidence

只有进入 Plan、round 切分、合同/bootstrap 变更或需要保留 review trail 时才写。落位：

- `docs/project-intake/`：项目 intake 与长期说明
- `operations/planning/`：Plan
- `operations/work_logs/`：执行记录
- `operations/reviews/`：reviewer 输出

普通 bounded task 不强制写 evidence。格式见 `docs/manual/document-governance.md`。

## Boundaries

- 治理层边界见 `AGENTS.md`，本文不复述。
- reviewer 不写 candidate 文件。
- 不为 trivial task 制造 durable evidence。
- 不因为仓库里有历史 Plan 或 operations 目录就自动加重流程。
