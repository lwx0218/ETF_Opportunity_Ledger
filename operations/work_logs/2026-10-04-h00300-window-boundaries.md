# H00300 复核修复：请求窗口与海外 D−1 边界

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 修复 2005 年硬截断及海外尾日可用性误判
- Timestamp (UTC): 2026-10-04T14:27:28Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮复核修复与条件合并授权；AGENTS.md；`docs/h00300-offline-restore.md`

## Goal / Changes

在 `codex/h00300-offline-restore` 的 `c3285b5` 上继续开发。移除 quality/build 的 2005 年固定起点；预检与正式 build 共用 `window_days` 和 `input_rows`。默认起点为官方日历首日，显式窗口超出可信首尾即阻断，不再用元旦前 14 天容忍推断休市。请求窗口、可信范围、实际窗口写入质量报告及面板 meta。

海外实际输入仅包含日期早于窗口最后一个 A 股交易日的原生行。只有尾日行情时明确阻断；未消费尾条单列且不做 OHLC 放行依据。保留窗口前指标预热及现有 D−1、stale/data_hole 规则。可信日历范围外原行情日期与已知非交易日分列。

同步 CLI `--start`、文档及回归用例。未修改真实数据库、规则、治理文件或日历，未抓行情、运行真实研究或执行恢复 apply。

## Validation

- 最终完整测试：`.venv/bin/python -m unittest discover -s tests -t .`，**302 tests，67.568s，OK**。
- 新增 10 项回归：2005 年前默认/显式窗口历史；早期缺收盘；CLI/预检/build/报告/meta 同窗；休市边界计数；可信范围外含元旦拒绝；海外三路由仅尾日；周末 end；合法 D−1 与未消费坏尾条；旧预热/断档规则；未知日历日期不误标休市。
- 独立只读 reviewer：**approve**，无阻塞问题；独立运行 quality+indicators 68 项通过，最后的未知日历日期分类增量另跑 4 项通过。
- 官方 Ponytail 4.10.3 `ponytail-review` 技能，Codex 宿主实际只读执行及增量复核：**Lean already. Ship.** 正确性由上一项单独复核。
- `git diff --check` 通过；真实行情库、规则及治理文件与 `df812b7` 无差异。
- 已 fetch 最新 main：`df812b7b2fb6613fad624aa407f5f209d3782641`；是任务分支祖先，合并树检查无冲突。没有把本地检查冒充 GitHub 必需检查。

## Authorization / Delivery

Owner 已授权本次及后续已批准范围内代码任务，在检查通过、无阻塞、与最新 main 无冲突并遵守分支保护/必需检查的前提下自行创建 PR 和合入 main，无需逐次询问。授权限代码合并；真实数据应用与研究执行仍须按各自任务授权。

当前标准 GitHub API 请求在代理 CONNECT 阶段即被 403 拒绝，`api.github.com` 不在现有出网允许域名中。已报告需要通过环境设置放行并生效；未修改网络设置、提取凭证或绕过代理。此状态不能查询 GitHub 分支保护/必需检查、创建 PR 或声称已合并。Git HTTPS 分支推送单独验证；最终远端结果与提交 SHA 见本次交付。
