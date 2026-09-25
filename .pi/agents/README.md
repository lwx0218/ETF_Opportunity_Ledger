# Agents

本目录定义 round 内的角色。执行合同以项目根 `AGENTS.md` 为准。

## 交付主线

1. `pi --name "00-orchestration"` — 澄清需求、收敛范围、切分 round
2. `/fleet` — 每个 round `session_spawn` 一个独立 session
3. round 内按宿主分配角色：Web UI 内置工具可用时用 `subagent_spawn`，匹配角色模板优先 `delegate_task`；CLI 或无 Web UI 工具时用独立 `pi-subagents`
4. `ponytail` 对新增代码做门禁

## 角色

| 文件 | 角色 | 角色约束 | 职责 |
| --- | --- | --- | --- |
| `builder.md` | builder | 可写 | 按 round 任务包实现最小可辩护改动 |
| `reviewer.md` | reviewer | 只读 | findings-first 复核，给出明确结论 |
| `planner.md` | planner | 只读 | 需要先收敛范围时使用，可选 |

默认只需要 builder + reviewer。范围不清时才加 planner。

这些文件供 CLI 的 pi-subagents 使用；Web UI 选择可用的匹配角色模板，或把同样的职责约束写入 `subagent_spawn` 任务。不假设 Web UI 自动加载 `.pi/agents/`。只读是角色约束，不是运行时沙箱承诺；不要求 Web UI 经 pi-subagents，也不为兼容升级或 patch 包。

## 启动 / 路由资源

- `/project-kickoff`：首 session 的 bounded discovery 与 Plan Preview
- `/governance-loop`：已有 baseline 的后续 bounded task
- `grill-me`：route 不稳定时做有界澄清访谈
- `domain-modeling`：仅在领域确实模糊时启用；确认前 no-write

## 边界

- reviewer 不写 candidate 文件。
- 治理层边界见项目根 `AGENTS.md` 的「治理层边界」一节。
- builder 不主动扩 scope；必须偏离任务包时先说明原因和影响。
