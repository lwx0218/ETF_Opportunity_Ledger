---
description: Establish an approved baseline plan before greenfield implementation
argument-hint: "<project request>"
---

# Project Kickoff

用于 greenfield 项目，或还没有 approved baseline 的项目。在 Orchestration session 里使用。

Project request:

```text
$ARGUMENTS
```

仓库已有稳定 baseline、且这次是后续 bounded task 时，直接说明并改走 `/governance-loop`，不要强行走 kickoff。

## No-Write 边界

Owner 确认规划前，你可以：

- 读仓库合同与已有 evidence
- 从仓库推断事实，而不是拿去问用户
- 分类请求、选择相关的 discovery 透镜
- 讨论范围、领域、约束、验收、假设和风险
- 在聊天里展示 Plan Preview

确认前不得：

- 修改业务代码或配置
- 创建或更新 Plan、`CONTEXT.md`、ADR、work log 或其他项目产物
- 安装依赖或执行破坏性 / 系统级操作
- 开始实现或声称开发有进展

bootstrap 在本次对话之前创建的文件属于既有脚手架，不是本次授权的写入。

## Bounded Decision Interview

- 默认最多 3 轮 discovery
- 每轮聚合 3–5 个相关的 blocking decision
- 总量目标上限 12–15 个
- 每个决策都带 recommended default，并说明为什么它足够安全
- Owner 可以直接回 `accept recommended defaults`
- 能从仓库推断的事实不要问
- 只在答案会改变范围/验收、架构/数据归属，或属于难以回退的高风险选择时才问
- 非阻塞的不确定性记为 assumption 或 backlog

每次 discovery 回复结尾给出：Resolved / Assumed / Blocking / Deferred / 剩余问题预算。

`domain-modeling` 只在术语、实体、状态流转、归属或 bounded context 确实模糊时启用；确认前保持 no-write。

## 终态

每一轮必须落在且只落在一个终态：

### 1. `blocking-decisions`

只给出有界决策和当前预算状态。

### 2. `ready-for-approval`

所有阻塞性的范围、架构、验收决策都已解决，非阻塞不确定性已记为假设或延后，验证方式清楚时使用。

在聊天里给出一份完整 Plan Preview，包含：

- Goal 和 source of truth
- in-scope / out-of-scope
- 架构与数据/领域归属决策
- 预计改动的文件或面
- 验收标准和具体验证方式
- 假设、风险、backlog
- **round 划分**：每个 round 说清目标、改动面、验证方式、完成判据
- durable evidence 路径
- 下一个人类控制点

结尾固定使用：

```text
以上 Plan 是否可行？是否还有需要继续确认或修改的地方？

- 如需修改：直接说明修改点
- 如无其他问题：回复"确认计划"
- 确认后我将持久化 Plan，并用 /fleet 分发第一个 round
```

### 3. `approved-and-persisted`

仅在 Owner 明确确认后使用。持久化 Plan，然后在 Orchestration session 里用 `/fleet` 为第一个 round `session_spawn` 开发 session。

接受 recommended defaults 不等于批准规划。要求 Owner 回复"确认计划"或等价的明确确认。要求修改则回到 Preview 修订；取消则不授权任何写入。

## 确认后

- 创建 / 更新项目本地 Plan 与 intake
- 用 `/fleet` 分发 round，round 间通过 `session_bus` 同步
- round 内由 builder / reviewer 执行，新增代码由 ponytail 门禁
- 治理层边界见项目根 `AGENTS.md`
