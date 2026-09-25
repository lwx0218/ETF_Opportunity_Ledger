---
description: Route an existing-baseline task through the minimal governance loop
argument-hint: "<bounded task>"
---

# Governance Loop

用于已有 baseline 的后续 bounded task。Greenfield / 无 baseline 请用 `/project-kickoff`。

Task:

```text
$ARGUMENTS
```

## Gate

- Goal:
- Source of truth:
- Entry points:
- Constraints:
- Outputs:
- 本次改动面（只有这一部分进入本次验收）:
- Route: `direct-execute` | `plan` | `review-only` | `needs-package`

先用仓库证据判断，不要一上来就问。route 仍不清楚时用 `grill-me`：最多 3 轮，每轮 3–5 个 blocking decision，每题带 recommended default。

治理层边界见项目根 `AGENTS.md`。

## Direct Execute

清楚的 bounded task：

- Execute:
- Verify:
- Result:
- Next step:

不要为 trivial task 制造 durable evidence。

## Plan

需要澄清范围、风险、验证或切分 round 时：

- Scope:
- Files expected to change:
- Validation:
- Round 划分（如需分发）:
- Assumptions / backlog:

切出 round 后回到 Orchestration session 用 `/fleet` 分发。round 只需说清目标、改动面、验证方式、完成判据。

## Review Only

- 复核对象:
- Findings:
- 结论: `approve` | `approve_with_follow_up` | `return_to_planning`

reviewer 不写 candidate 文件。

## Needs Package

- 缺失能力:
- 为什么现有 package 不够:
- 建议的下一步:

## Closeout

- 改了什么:
- 验证结果:
- 遗留风险 / 未覆盖项:

区分本次改动、既有无关改动和生成产物，不要把无关变更算进本次交付。
