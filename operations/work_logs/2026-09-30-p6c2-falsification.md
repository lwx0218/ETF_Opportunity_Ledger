# P6c-2 · 「证伪」判定（schema v1.1-f）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §9 P6c-2——`src/ledger/` + `src/jobs/` 实现 `docs/etf-card-schema-v1.md` v1.1-f，`TERMS_VERSION` 升一版（不阻塞 V1）
- Timestamp (UTC): 2026-09-30
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示「先做 P6c-1，再做 P6c-2」）
- Source of truth: schema v1.1-f；replan §9；main `4772cb7`

## 结果

| 项 | 结果 |
|---|---|
| 出场记录 | `exits` 加 write-once 字段 `exit_signal_close`（触发出场的那根收盘，研究序列上，必填、> 0）。存储层核对两条：已有出场日及以前的每日行时，它必须等于最近那一行的收盘（不能随手填一个高于失效位的数躲开证伪）；`失效位` 出场时它必须低于锁定失效位（v1.1-f「失效位出场必然满足第一条」） |
| 期满核对 | `finals_insert` 触发器与 `mechanical_score` 同一口径：先判证伪（`exit_signal_close` < `cards.invalidation_price`，或 `exit_reason = 论点作废`），未证伪的卡按锁定菜单分档；菜单第 2 项「未达」= `realized_r ≤ 0`，去掉 −1 下限 |
| `mechanical_score` | 改为 `mechanical_score(card, exit_row)`，直接读卡片与出场记录的字段，避免调用方传错参数顺序 |
| 每日任务 | 止损离场时写 `exit_signal_close` = 上一行每日记录的收盘（它跌破了当时生效的止损）；期满调用新的 `mechanical_score` |
| 统计 | `summary()` 加 `falsified_thesis_void_positive_r`：论点作废而证伪、但 R > 0 的卡数（v1.1-f「报告时单列，不加字段」） |
| 旧库 | `SCHEMA_VERSION` `v1.1` → `v1.1-f`；P6b 建的 `v1.1` 回放库打开即拒绝，不写迁移（正式台账未启用，A7） |
| `TERMS_VERSION` | `jobs-daily-v1` → `jobs-daily-v2`；之前填的 `jobs-daily-v1` 不再算数；`config/ledger-rules.json` 说明同步 |
| 测试 | `python -m unittest discover -s tests -t .`：173 个全过（新增 3 个）。§9 的四例 × 两项菜单全部走存储层（错的档写不进、对的档写得进，Python 与 SQL 一致）：失效位出场次日高开（−1 < R < 0）→ 证伪；移动止盈出场但收盘低于锁定失效位 → 证伪；论点作废且 R > 0 → 证伪；未证伪但跳空致 R ≤ −1 → 未达。另测触发收盘必须与台账一致、失效位出场的收盘必须在线下、`v1.1` 旧库拒绝；每日任务的生命周期测试断言写入的触发收盘 |
| 文档 | `docs/ledger-storage.md`（exits / finals 行、schema 版本、统计、待决第 5 条改为已统一）、`docs/jobs-daily.md`（口径版本、期满核对、记账口径表） |

## 交 Cowork 留意

- **没有每日行的卡**：`exit_signal_close` 只能对照已写入的每日行核对。出场前一行每日记录都没有的卡（例如进场当天就手动出场）存储层只要求它为正数。每日任务的路径不会出现这种卡（进场当天收盘就追加每日行，最早次日开盘才会离场）。
- **手动 / 论点作废出场的「触发收盘」**：每日任务目前不自动做这两种出场（论点失效只提醒）。实现按「出场日及以前最近一行每日记录的收盘」取值；论点作废不论收盘都判证伪，手动出场则用这根收盘与失效位比较。若手动出场要改用别的时点（例如决定出场当天的盘中价），需在 schema 写明。
