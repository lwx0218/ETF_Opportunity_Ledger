# 腾讯价格指数离线导入：实现与复核

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 000852 / 000905 固定证据批次离线导入
- Timestamp (UTC): 2026-10-06T05:19:05Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮指令及已有代码合并授权；357d2f3 报告与证据索引；AGENTS.md；docs/data-layer.md

## 改动

从最新 `main=a78e074` 创建 `codex/tencent-price-index-offline`。新增 `offline-tencent-price --recorded-dir DIR [--db DB] [--apply]`，默认真只读。固定索引 SHA256 与 357d2f3 原文件相同；只处理 000852 / 000905、44 个年度响应。没有联网、替换索引、增加代码或强制覆盖入口。

重验原文 bytes/hash、请求源与唯一参数、业务状态、身份代码和名称、时刻、日期/OHLC、官方日历、索引统计和跨窗重叠。窗外原行先验证后裁剪。写入独立 `tencent_price_index_offline` 来源、raw 价格序列；volume/amount=NULL，price_only=true 在同一 backfill 的顶层及逐序列审计登记。原文索引与 44 个响应随 runs.args 保存，requests 保留完整请求元数据，每条行情保留所属年度的 fetched_at。

apply 使用单事务，只补缺行；已有行逐字段不一致、证据外额外 raw 行或已有审计损坏均拒绝。coverage、universe、日历、执行行情、全收益序列及旧审计不改；旧日期约束库仍需显式升级，不自动迁移。

## 验证结果

| 检查 | 实际结果 |
| --- | --- |
| 腾讯离线专项，开发 SQLite 3.53.1 | 21 项通过，最终审计回归后 11.355 秒 |
| 腾讯离线专项，精确 SQLite 3.42.0 | 21 项通过，最终审计回归后 11.977 秒 |
| 全套，开发 SQLite 3.53.1 | 393 项通过，68.112 秒，无跳过 |
| 全套，精确 SQLite 3.42.0 | 393 项通过，72.832 秒，无跳过 |
| 独立 correctness review | **approve**；独立在两环境跑 21 项，另针对三类审计损坏复验拒绝和保全 |
| Ponytail 4.10.3 官方 skill | **Lean already. Ship.**；另实际 21 项 smoke，12.098 秒通过 |
| CLI / Pi 命令 | help 正常；文档两个 Python 块编译通过，backup 块已实际执行 |
| 原件缺失行为 | 实际正式库的隔离副本 dry-run 与 apply 均拒绝，副本逐字节不变 |
| 格式与基线 | git diff --check 通过；末次 fetch main 仍为 a78e074，无冲突 |

测试全部使用合成原文与临时库：覆盖 44 个年度窗口、合法闰日、窗外重叠、错误/缺失/重复/非交易日、错身份/URL/哈希、非有限或倒置 OHLC、获取时刻边界、路径逃逸、NULL 量额、保留完全一致旧行、完整审计、坏审计、幂等与中途事务回滚。逐表验证 meta/calendar/coverage/universe/update_results、其它 bars 和历史 runs/requests 保全，包含全收益与合法非交易日原行。

独立复核初次发现：旧审计 args 损坏或标记丢失会被跳过，重跑可能追加新审计掩盖。已修复为按批准的原请求 URL+hash 关联扫描所有作业，再严格验证 kind/标记/原文/登记。新增坏 JSON、空对象、删除或 false 标记、改 source/price_only/kind、删 requests 回归；无关历史坏 JSON 原样保留。修复后全套重跑通过。

正式行情 SHA256 始终为 `8fa89a71c2afad92204f0c00a343f031e6108db37e0e76e2b828b41f8f72e0af`。证据索引 SHA256 始终为 `f2865c4884cc9d5c290c03f17afc75c2a74550376d31a2f9cbb1174c30a8603b`。未改策略参数、规则/cron、治理文件或正式数据库；未运行正式研究。全套中的研究输出仅来自已有合成 fixture。

## Pi 交付与真实验证边界

本工作区没有 `outputs/data/tencent-price-candidates-20261006/recorded/`，所以没有执行真实原响应解析或真实入库。报告中的每代码 5,282 行来自已批准的 357d2f3，不能拿合成测试冒充真实复验。Pi 须使用自己保存的 44 原件，先副本验证再正式 apply；缺文件、哈希不同或其它冲突应停止报告。

副本建立、dry-run、apply、幂等哈希核对、其它历史双向 EXCEPT 保全检查及正式命令见 [操作说明](../../docs/tencent-price-index-offline.md)。本机副本与测试日志在忽略的 `outputs/tencent-price-import-validation/`，不入 Git。

本地门禁已全部通过；按授权推送并尝试 PR/合并，最终消息报告远端实际结果。不得因本地通过跳过远端分支保护及必需检查。
