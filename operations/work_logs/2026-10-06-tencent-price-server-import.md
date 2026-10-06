# 腾讯价格指数候选 · 服务器离线入库检查点

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 固定原件批次副本复验、正式离线入库及合并分支清理
- Timestamp (UTC): 2026-10-06T07:21:01Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮授权；docs/tencent-price-index-offline.md；main 6e5d017

## 结果

| 校验 | 结果 |
|---|---|
| 代码/测试 | main包含6e5d017；393 tests / OK（临时合成测试，非正式研究） |
| 真实证据 | 固定357d2f3索引SHA256 `f2865c4884cc9d5c290c03f17afc75c2a74550376d31a2f9cbb1174c30a8603b`，44年度原响应bytes/hash/HTTP/身份/时间/窗口/日历/OHLC全部重验 |
| 新增行情 | 000852与000905各5,282行，2005-01-04～2026-09-30，共10,564行；raw/source=tencent_price_index_offline，volume/amount全部NULL，原量留原文 |
| 审计 | 仅新增backfill run 6、44 requests与上述bars，runs计数器+1；内嵌完整索引/响应、日历hash、证据commit/执行commit、price_only=true及插入日期分区 |
| 历史保全 | 副本与正式库均逐表双向EXCEPT通过；全部旧bars/runs/requests、coverage/latest、calendar、universe、meta、update_results及schema不变；H00852/H00905全收益不覆盖，正式研究选择不改 |
| 幂等/完整性 | 两库dry-run不写；第二次apply均changed=false/idempotent=true/rows_to_insert=0，字节SHA256不变；integrity_check=ok、foreign_key_check空、DELETE模式、无热日志 |

## 执行证据与边界

`outputs/tencent-price-import-validation-6e5d017/` 保存tests、日期约束审计（已有gregorian-v1，无需升级）、before/copy副本、dry/apply/repeat、逐表保全与正式执行报告、hash；正式写前 `formal-before.sqlite` 为字节精确备份，原SHA256 `8fa89a71c2afad92204f0c00a343f031e6108db37e0e76e2b828b41f8f72e0af`。独立只读review approve，执行者复核后才正式apply。原件继续在 `outputs/data/tencent-price-candidates-20261006/recorded/`，不入Git。

价格指数不是全收益；qfq参数不改变价格口径或成为ETF hfq。量单位未核实所以NULL，不借价格OHLC拼全收益close；日期、来源与原fetched_at保留。主题回填、指数≠ETF（研究每年1%折扣）、腾讯减法qfq及价格/全收益混用陷阱仍适用。仅库与本页提交检查点，不改业务代码、正式序列选择、不运行build/收益/研究或启用规则/cron；coverage未引用候选，因此不将候选冒充已选研究序列，不重打研究包。

## 远端分支清理

删除前重新 `git fetch origin --prune`，以下头SHA逐个确认被origin/main包含，使用 `--force-with-lease=refs/heads/<branch>:<SHA>` 删除。全部成功，无未合并或lease失败分支；保留main。详细输出在同目录 `branch-cleanup.json`。

| 分支 | 删除时头SHA |
|---|---|
| codex/h00300-offline-restore | 6b2fff24c23dbb4f935709597f3a529c8354685d |
| codex/sqlite-date-constraints | a7a6f39e451e4df9b9cd008282539bdb9d097fb9 |
| codex/h00300-year-end-supplement | d8272b9203e3e2a5d9490939e8bde5529bc43d8a |
| work/parallel-data-and-product | 6b30299fc5dc19d2c603e71fa3b63703c1c48832 |
| codex/runnable-opportunity-ledger | ba167ed2eecd1ef68ad44aa5ac27b9739c5c49f8 |
| codex/tencent-price-index-offline | 722554d62e4da9c999b6eee7249de697bf29926b |
