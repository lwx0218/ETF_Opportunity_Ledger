# Document Governance

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: manual-reference
- Status: active
- Owner: project owner
- Last updated: 2026-08-30
- Source of truth: AGENTS.md

## Purpose

本文定义 `ETF_Opportunity-Ledger` 的轻量文档治理规则，用于统一新增或实质更新 Markdown 时的目录边界、命名、Metadata 和 evidence 写入条件。

## Scope

适用范围：

- `docs/**`：长期说明、manual、reference、project intake 和导航文档
- `operations/**`：Plan、work log、review、manifest、变更记录等 durable evidence
- `assets/templates/**`：可复用模板（如项目本地存在）

不适用范围：

- archived historical evidence：`operations/archive/**` 保持历史原貌
- 第三方原文、许可证、外部引用
- 代码、配置、测试、生成产物

## Directory Meaning

### `docs/**`

`docs/**` 承载相对稳定的说明性文档。它应该回答“这个项目/机制是什么、为什么存在、怎样使用”。

建议子类：

- `docs/manual/**`：操作与治理 reference
- `docs/project-intake/**`：项目 intake 与启动信息
- 未来项目如有产品文档，可用 `docs/product/**`，但必须由项目本地合同定义

### `operations/**`

`operations/**` 承载事件型 durable evidence。它应该回答“哪一次任务、什么时候、谁批准、做了什么、验证结果是什么”。

建议子类：

- `operations/planning/**`：Plan / scope / acceptance / stop conditions
- `operations/work_logs/**`：执行记录和验证记录
- `operations/reviews/**`：正式 review artifact
- `operations/archive/**`：历史证据归档，不进入默认 active navigation

## Naming Rules

### Stable docs

稳定说明文档使用 kebab-case：

```text
docs/manual/document-governance.md
docs/project-intake/project-overview.md
```

规则：

- 小写英文、数字、连字符；
- 文件名表达主题，不强制日期；
- README 只用于目录导航；
- 避免 `final`、`new`、`temp`、`copy` 等状态词。

### Operations evidence

事件型 evidence 使用日期前缀加主题：

```text
operations/planning/2026-08-30-example-task.md
operations/work_logs/2026-08-30-example-task.md
operations/reviews/2026-08-30-example-task-review.md
```

规则：

- `YYYY-MM-DD-<slug>.md`；
- slug 用 kebab-case；
- 同一任务的 plan/work log/review slug 尽量一致；
- legacy 子目录可保留历史结构，归档后不强制重命名。

## Required Metadata

新增或实质重写的 `docs/**` Markdown 应包含最小 Metadata：

```markdown
## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: manual-reference | intake | guide | index | template | other
- Status: draft | active | archived
- Owner: project owner
- Last updated: YYYY-MM-DD
- Source of truth: AGENTS.md or path/to/source.md
```

新增 `operations/**` evidence 应包含任务型 Metadata：

```markdown
## Metadata

- Project: ETF_Opportunity-Ledger
- Task: <task name>
- Timestamp (UTC): YYYY-MM-DDTHH:MM:SSZ
- Owner: project owner
- Route: direct-execute | plan | review-only | needs-package
- Source of truth: AGENTS.md or approved Plan path
```

## Minimal Body Shape

### `docs/**`

推荐结构：

1. `# Title`
2. `## Metadata`
3. `## Purpose`
4. `## Scope`
5. task-specific sections
6. `## Related Files`（如适用）

### `operations/**`

推荐结构：

1. `# Title`
2. `## Metadata`
3. `## Goal / Summary`
4. `## Scope / Changes`
5. `## Validation`
6. `## Decision / Next Steps`

## Update Policy

- 小修可只更新相关段落。
- 实质更新时同步刷新 `Last updated` 或 event timestamp。
- 不为满足格式而批量重写历史 archive。
- 模板应放在 `assets/templates/**`；项目本地没有该目录时，不把模板放入 `operations/**`。
- Active README/index 只做导航，不承载隐藏流程义务。
- 产品、领域、安全和 runtime source-of-truth 仍必须由项目本地合同定义。

## Related Files

- `AGENTS.md`
- `Harness_manual.md`
