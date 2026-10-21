# ETF_Opportunity-Ledger Harness Manual

<!-- HARNESS:MANUAL:MANAGED:START -->
项目本地的人类操作入口。模型执行合同以 `AGENTS.md` 为准。

## 交付主线

| 环节 | 承担者 | 做什么 |
| --- | --- | --- |
| 1. 按需规划 | 当前会话与 Owner | 范围不清时澄清，必要时切分 round |
| 2. 按需委派 | 当前会话 | 不使用 `/fleet` 分发，不要求独立 Pi session |
| 3. 执行 | 当前会话；必要时子代理 | 清楚且已授权的任务直接执行并验证；并行或专门复核时才委派 |
| 4. 门禁 | `ponytail` | 新增代码准入判定 |

需要规划时由你确认范围与 round 划分；已授权的清楚任务不重复增加审批。使用 reviewer 时由其出复核结论，代码准入仍由 ponytail 判定。

委派按需使用当前宿主可用的能力，匹配角色模板优先；不以子代理、Fleet 或终端复用器是否可用阻塞可直接完成的任务，不为分发安装或兼容适配包。reviewer 的只读是角色约束，不是运行时沙箱承诺。

## 第一次 session

```bash
pi --name "00-orchestration"
```

批准规划前保持 no-write：只读取、推断、讨论和展示 Plan Preview；不改业务文件、不写 durable evidence、不安装依赖、不执行破坏性操作。

Plan Preview 应让你能检查 goal、scope、non-goals、assumptions、risks、validation 和 round 划分。接受 recommended defaults 不等于批准规划。

## 执行 round

本项目不再通过 `/fleet` 分发任务。规划确认后可在当前会话逐项执行 round，不要求每 round 新建 session，不要求 `session_spawn` / `session_bus` 或终端复用器。

确需并行或专门复核时再委派，并明确目标、改动面、验证方式和完成判据；分发本身不是门禁。旧模板或历史记录中的 Fleet 前置步骤不再适用，以 `AGENTS.md` 的项目 owned 约定为准。

## 已有 baseline 后

清楚的 bounded task 直接执行并验证，不必每次都开 Orchestration。不要因为仓库里有历史 Plan 或 operations 目录就自动加重流程。

## Evidence

项目 evidence 默认保存在 `docs/project-intake/`、`operations/planning/`、`operations/work_logs/`、`operations/reviews/`。

普通 bounded task 不强制写 evidence。需要记录时写最小、可复验内容。新增 Markdown 前先按 `docs/manual/document-governance.md` 判断落位。

## 更新治理面

从 `Harness_Workspace` 根：

```bash
sh harness.sh <本项目目录>           # 预览
sh harness.sh <本项目目录> --apply   # 写入
```

它管理 Harness 分区与 `.pi` capability surface，保留项目 owned 内容，会显示 manifest 和备份路径，不自动 commit 或 push。

`npm:pi-web-ui` 默认不下发，使用互斥的 `--with-web-ui` / `--without-web-ui` 加入或移除项目声明；后者不禁用全局 UI。旧 Dashboard 开关会报迁移指引。`pi-subagents` 仍默认下发供 CLI 使用。

工具自动迁移项目/执行环境全局的已知 Dashboard 声明（`@blackbelt-technology/pi-agent-dashboard`、`@blackbelt-technology/pi-dashboard-extension`）到 Web UI，已有 Web UI 锁版与对象字段保留；只有准确关联的 Dashboard bridge 声明和记录会被清理。没有 Dashboard 且无 UI 开关时不调整已有 UI。

预览分别显示 Project / Global 差异；**全局替换影响使用该配置的所有项目**。只有 `--apply` 在项目检查通过后备份并原子写全局，路径为 `Global Backup:`；全局失败时项目可能已更新，可修复后重跑。`init` 仍直接创建项目，但无 `--apply` 不写共享全局配置。不卸载包、不停止服务、不删除会话，不自动安装依赖。

全局路径优先 `PI_AGENT_DIR/settings.json`，否则兼容 `PI_HOME/settings.json`；都未指定时依次查找 `~/.pi/agent/settings.json`、`~/.pi/settings.json`、`~/.config/pi/settings.json`。显式路径不回退；非法配置或不安全 symlink 拒绝执行。`--no-global-dedup` 仅关闭重复声明去重，不关闭检测迁移；项目显式锁版与对象声明不被全局去重删除。

## Safety

遇到破坏性操作、外部授权、scope 改变、无法验证或 managed/project 分区不清时停下来让 Owner 决策。不自动 push。
<!-- HARNESS:MANUAL:MANAGED:END -->

<!-- PROJECT:OWNED:START -->
## 项目操作说明

启动命令见 README.md。现状与待办见 docs/status.md。

### 当前任务执行约定（2026-10-21）

项目不再通过 `/fleet` 分发。清楚且已授权的任务在当前会话直接执行并验证，委派按需；Fleet、独立 session、终端复用器和强制子代理均不是前置门禁。此约定对应 `AGENTS.md` 的项目 owned 条款；Harness 同步或旧 `.pi/` 模板不得恢复旧分发要求。

`pi --name "00-orchestration"` 的首次规划说明仅适用于 greenfield / 无 baseline 场景，不是已有项目每次任务的必经步骤。初始化授权不等于业务实施授权。不运行未授权研究，不自动安装依赖或修改全局配置；项目冻结状态不因本次文档更新而解除。

Package 与全局依赖说明见 `README.md`。包的历史声明不构成任务流程要求，换机器不再要求先核对 Fleet；仅在实际需要某项能力时核对对应包。不因本次文档修改安装、卸载或调整任何包。

本次 Owner 已授权初始化后的单次 GitHub 推送，后续推送仍需另行授权。
<!-- PROJECT:OWNED:END -->
