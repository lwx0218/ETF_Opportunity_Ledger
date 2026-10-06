# 可运行机会台账交付与复核

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 三态产品接线、隔离演示与已定评分审查
- Timestamp (UTC): 2026-10-06T03:42:53Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮代码与合并授权；operations/planning/2026-10-06-parallel-data-and-product.md；AGENTS.md

## 交付

从最新 `main=60196ae` 创建 `codex/runnable-opportunity-ledger`。标准库薄 HTTP API、无构建依赖的前端、本地 Geist 字体、深浅主题；首页过去 / 当下 / 未来及已结 / 作废，同页冻结详情与每日 R，独立评分、作废、信号、推进和重置均接实际领域方法。先启动首版并交深浅截图及命令，再实现评分审查接线。

演示库位于忽略的 outputs 目录，版本 `web-demo-v2`，只用合成 OHLCV 和演示论点。已有指标计算 ATR/RS/z/形态，预热不足的 z 为 NULL；DailyJob 使用不变的 Params，所有卡由 Ledger 正规方法生成。旧演示版本明确拒绝，不自动覆盖。正式规则、策略参数、治理文件、研究流程及正式数据库均未修改。

正式入口用真正只读连接，缺库不建。HTTP 不接受任意库路径、时钟、冻结字段、手工成交；同源、Host、CSRF 与 revision 检查保护本机入口。API 不披露 agent 个体评分、理由或分桶，Owner 独立评分和未评分计数保留；未满 30 条不提供校准结论。

复用现有 summary/calibration；两条已定告警为最近 20 张已结平均已实现 R ≤ −0.2、全部已出场中手动比例 > 30%。反事实只展示冻结点位和已入账所选基准超额。随机抽样、双基准同期端点核对、季度反向、年度起算及容器结构变化证据明确待完成；不冒称 R6 全部交付，不自动裁定审查结果。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| SQLite 3.53.1 / Python 3.12 开发环境全套 unittest | 372 项通过，57.757 秒，无跳过 |
| 精确 SQLite 3.42.0 全套 unittest | 372 项通过，60.290 秒，无跳过 |
| JS `node --check` / `git diff --check` | 通过 |
| 独立 correctness reviewer | **approve**；另独立运行 Web 17 项 + scoring 11 项，最终兼容修复后再次确认 |
| Ponytail 4.10.3 官方 review skill | **Lean already. Ship.**；3 处未使用兼容/样式/别名已删除，API+scoring 19 项 smoke 通过 |
| 浏览器 Chromium 151 + Playwright 1.63.0 | 1440/390 宽深浅首页和详情均无 JS/console/请求错误或水平溢出 |
| 浏览器完整交互 | 独立评分、候选作废保留分母、手动及论点作废信号、次日成交进入过去、只读、重置均通过 |
| 正式行情保全 | 启动/浏览/测试前后 SHA256 相同，见下 |
| 正式台账 | `data/ledger.sqlite` 始终不存在；没有自动创建 |
| main 冲突 | 最后 fetch 仍为 60196ae，当前分支以它为祖先，无冲突 |

正式行情 SHA256：`8fa89a71c2afad92204f0c00a343f031e6108db37e0e76e2b828b41f8f72e0af`。

首次旧 SQLite 全套发现新增测试使用其 pysqlite 运行器未提供的 `iterdump()`，产生 1 个 ERROR；已改为 `total_changes` 前后比较并保留 `query_only` 拒写验证，真实临时文件字节保全仍由 HTTP 测试覆盖。最终两环境从头完整重跑均通过；没有跳过失败测试。全套中的研究输出来自现有临时合成 fixture，不是正式研究运行。

浏览器证据与 8 张截图在忽略的 `outputs/product-preview/`：`browser-validation.json`、`smoke.json`、`{home,detail}-{dark,light}[-mobile].png`。测试完整日志亦复制到该目录。重型截图不入 Git。

字体来自官方 npm `geist@1.7.2`，TLS 与 npm SHA512 integrity 核验通过，OFL 许可证随文件分发。两个字体 SHA256：

- Geist：`a369fcf5628ea2aa4e1b9e2ec6a5b3624e365bda588e1f0f2f12b564f728fbb8`
- Geist Mono：`fba8f577f38a2bbcbe818efa6348dd58f36303a10b8737c42fefad275be563ab`

## Pi 启动与复验

```bash
.venv/bin/python -m src.web --port 8765
# 本机浏览器 http://127.0.0.1:8765；正式只读 /?mode=readonly
.venv/bin/python -m unittest discover -s tests -t .
node --check src/web/static/app.js
sha256sum data/market.sqlite
```

完整首次安装、只读模式、SSH 转发、演示版本与边界见 [可运行台账说明](../../docs/runnable-ledger.md)。cloud-environment-onboarding 的 `start_skill` 已保存包含上述启动与检查说明；配置草稿保存不等于环境已发布，需要在环境设置中保存并发布才影响后续环境。

## 推送与合并状态

本地门禁已通过，允许按 Owner 授权推送任务分支和创建 PR。GitHub API 检查 `gh pr list` 返回 `Post https://api.github.com/graphql: Forbidden`；不能据 Git HTTPS 可用推断 PR/合并权限，也不绕过分支保护。任务最终消息及后续提交记录报告实际推送、PR 创建和合并结果。
