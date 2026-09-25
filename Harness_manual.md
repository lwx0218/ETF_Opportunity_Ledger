# ETF_Opportunity-Ledger Harness Manual

<!-- HARNESS:MANUAL:MANAGED:START -->
项目本地的人类操作入口。模型执行合同以 `AGENTS.md` 为准。

## 交付主线

| 环节 | 承担者 | 做什么 |
| --- | --- | --- |
| 1. 规划 | Orchestration session | 澄清需求、收敛范围、切分 round |
| 2. 分发 | `pi-fleet` | 每个 round 一个独立 Pi session |
| 3. 执行 | 按宿主选择子代理 | Web UI 内置工具；CLI 用 `pi-subagents`，分配 builder / reviewer |
| 4. 门禁 | `ponytail` | 新增代码准入判定 |

**你只需要介入第 1 步**：确认规划与 round 划分。round 内的复核结论由 reviewer subagent 出，代码准入由 ponytail 判定。

Web UI 内置工具可用时使用 `subagent_spawn`，匹配角色模板优先 `delegate_task`；CLI 或无 Web UI 工具时使用独立 `pi-subagents`，不做兼容适配。reviewer 的只读是角色约束，不是运行时沙箱承诺。

## 第一次 session

```bash
pi --name "00-orchestration"
```

批准规划前保持 no-write：只读取、推断、讨论和展示 Plan Preview；不改业务文件、不写 durable evidence、不安装依赖、不执行破坏性操作。

Plan Preview 应让你能检查 goal、scope、non-goals、assumptions、risks、validation 和 round 划分。接受 recommended defaults 不等于批准规划。

## 分发 round

规划确认后，在 Orchestration session 里：

```
/fleet
```

为每个 round `session_spawn` 一个开发 session（名字用 round 标识），round 间通过 `session_bus` 同步状态。不要靠人工复制上下文交接。

需要终端复用器（tmux / Ghostty / Zellij）。配置在 `~/.pi/agent/pi-fleet.json`。

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

当前只有最小 bootstrap，无业务启动命令。先读 `docs/project-intake/etf-opportunity-ledger.md` 全文（尤其 §1 / §3）；权威文档、数据、源码及 Teardown 设计资产仍待导入，五项 Owner 决策仍未决。

进入项目目录执行 `pi --name "00-orchestration"`，完成材料核对和实施 Plan Preview；本次初始化授权不等于业务实施授权。不运行研究，不自动安装依赖或修改全局配置。

Package 与全局依赖说明见 `README.md`：参考项目的 subagents / frontend-check 版本保留，Web UI 不作项目声明，Fleet 使用当前服务器全局声明，Ponytail 按 Harness 必需合同下发。换机器先核对 Fleet；尚未进行 package 运行验证。

本次 Owner 已授权初始化后的单次 GitHub 推送，后续推送仍需另行授权。
<!-- PROJECT:OWNED:END -->
