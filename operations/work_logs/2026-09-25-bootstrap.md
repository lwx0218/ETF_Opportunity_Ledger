# 最小初始化记录

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 最小 Harness 下发与首次提交
- Timestamp (UTC): 2026-09-25T09:05:36Z（本次初始化检查开始）
- Owner: Faye
- Route: direct-execute
- Source of truth: AGENTS.md；Owner 在本次会话授权最小下发、排除 pi-web-ui、参考 serenity_quant_research packages，并允许初始化后推送一次

## 范围

- 使用 Harness 原生 `harness.sh <target> ETF_Opportunity-Ledger --without-web-ui` 初始化；未修改 Harness_Workspace、参考项目或全局配置。
- 保留原生 managed 分区、角色、skills、prompt templates、交付清单与文档规范；只在项目 owned 分区落实领域合同。
- `docs/project-intake/etf-opportunity-ledger.md` 保存 Owner 的 init-v1 §0–附及初始化边界；README 提供中英 description 和接手入口。
- 参考项目的 `pi-web-access`、`pi-subagents@0.60.0`、`pi-frontend-check@1.1.0` 保持一致；排除其 `pi-web-ui@0.95.0`。
- `@dietrichgebert/ponytail` 是 Harness 必需项，参考项目 settings 未声明且本机全局未声明，故保留 starter 的项目声明。Fleet 已由当前服务器全局声明，按 Harness 去重；已有全局 Web UI 未禁用或修改。
- 仅下发 package 声明，不安装依赖、不复制第三方源码、不运行子代理或产品开发 round；尚未验证 package 运行时。
- 加入 `.gitignore`，排除认证、缓存、数据库、批量行情与输出；保留将来 `data/universe.csv` 的可跟踪入口，但没有生成该文件。

## 已看过什么 / 未做什么

仅阅读 Owner 提供的初始化文档、Harness 配置及模板、参考项目的 `.pi/settings.json`、当前服务器全局 package 声明和 Pi package 使用文档。未读取行情数据、未调用市场数据源、未计算统计或回测；Owner 提供的历史结论和接口可用性未独立复验。

八份 QTradeResearch 文档、现有数据和源码、Teardown design-rules v3 / tokens.css 均未导入；没有补造 schema、主题清单或规则。五项 Owner 决策仍未决，任务 0–7 均未开始，未创建实施 Plan 或把初始化当作实施批准。

## 验证（提交前）

- GitHub `git ls-remote --symref <origin> HEAD` 检查成功、无 HEAD 返回；目标目录检查为不存在，随后初始化独立 `main` 仓库。
- JSON 解析、项目名、package 集合比对通过：参考项目减 Web UI，加 Harness 必需 Ponytail。
- managed 内容与 canonical starter 逐段一致，managed / owned 标记配对；无未替换的项目名或 slug 占位符。
- intake §0–10 与术语均存在；无 `src/` 或 `data/`，未冒充已有资产。
- `git check-ignore` 验证认证、缓存、行情、输出、数据库被排除，`data/universe.csv` 不被排除。
- `sh harness.sh <target> --without-web-ui` 二次 dry-run：项目与全局均 `OK no changes`，无文件待变更。
- staged diff / whitespace / 文件清单检查通过，26 个文件均为治理模板、配置、说明与初始化记录，无业务代码、数据、依赖或认证文件。
- 新仓库无 Git 作者配置；复用参考项目已有作者信息，仅配置新仓库本地 `user.name` / `user.email`，不改全局。一次普通 push 的实际结果在交付消息中报告，不使用 force、不额外推送。

## 下一步

先导入权威材料、解决影响当前任务的 Owner 决策并批准实施规划，再按 intake 任务顺序开发。迁移到其它服务器先核对全局 Fleet。业务运行、数据源连通性与研究结论不在本次初始化验收范围。
