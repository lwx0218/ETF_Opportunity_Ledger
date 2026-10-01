# P6d-2 · 出场信号持久化到成交（schema v1.1-g 第 3 条）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §10 P6d-2——`src/ledger/` + `src/jobs/` 实现 `docs/etf-card-schema-v1.md` v1.1-g 第 3 条，`SCHEMA_VERSION` 与 `TERMS_VERSION` 各升一版（不阻塞 V1）
- Timestamp (UTC): 2026-10-01
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示「先做 P6d-1，再做 P6d-2」）
- Source of truth: schema v1.1-g；replan §10；main `3375a58`

## 结果

| 项 | 结果 |
|---|---|
| 出场信号表 | 新表 `exit_signals(card_id, signal_date, reason, manual_reason, signal_close, recorded_at)`，write-once、每张卡至多一条、不可改删。存储层核对：已进场未出场；信号日不早于进场日、不晚于数据库时钟；**信号日必须已有每日行且 `signal_close` 等于它的收盘**（第 1 条 (a) 改为对信号行）；信号日之后已有每日行时不能补记更早的信号；`失效位` 信号收盘必须低于锁定失效位（第 1 条 (b)）；`手动` 必须写理由 |
| 出场记录 | `exits` 必须引用信号：`exit_date` 晚于信号日，`exit_reason` 与 `exit_signal_close` 都等于信号的原因与收盘。原「出场日之前最近一行」的核对删去（两者只在顺延时不同，v1.1-g 以信号行为准） |
| 每日任务 | 收盘每日行追加后，收盘跌破当时生效的止损 → 写信号（启用过移动止盈记「移动止盈」，否则「失效位」）；此后止损冻结，不再上移。开盘离场改为处理未成交的信号：第一个有开盘价的交易日按开盘成交，没有开盘价就顺延、信号不撤销（与 V1 引擎的 `exit_flag` 一致）。手动 / 论点作废由 owner 收盘后调 `Ledger.signal_exit` 声明，次日开盘由每日任务成交——同一条路径 |
| 视图 | `card_status` 加 `exit_signal_date`、`exit_signal_reason`（在途卡是否已有未成交信号一眼可见） |
| 版本 | `SCHEMA_VERSION` `v1.1-f` → `v1.1-g`（旧库拒绝打开、不迁移）；`TERMS_VERSION` `jobs-daily-v2` → `jobs-daily-v3`（之前的确认不算数）；`config/ledger-rules.json` 说明同步 |
| 测试 | `python -m unittest discover -s tests -t .`：189 个全过（比 main 净增 6 个；P6c-2 的三条「最近一行」核对测试换成五条信号测试）。每日任务：止损次日没有开盘价、当天收盘回到止损之上，第三天开盘仍出场，触发收盘是跌破那一行，期满证伪；激活移动止盈后跌破、顺延期间收盘大涨，止损不上移；手动与论点作废走同一条路径（论点作废证伪）；三个场景都与 V1 引擎（`prereg_v1.engine.simulate`）用同一组构造数据比对出场日、价格与原因，完全一致。存储层：信号收盘必须等于信号行、write-once；没有信号不能出场、不能同日出场、原因与收盘必须取自信号、顺延成交可以；不能事后补记更早的信号、出场后不能补行；失效位信号必须在线下 |
| 文档 | `docs/ledger-storage.md`（出场信号行、出场行、schema 版本、待决第 5 条）、`docs/jobs-daily.md`（口径版本、开盘离场、收盘每日行、记账口径表） |

## 交 Cowork 留意

- **顺延期间 MFE / MAE 照常记**：v1.1-g 只说「不更新移动止盈」。实现冻结止损，但每日行的 MFE / MAE 仍按收盘记（卡片在成交前仍持有）。V1 引擎在 `exit_flag` 之后不再更新 `hi_close`，所以 `trail_quality`（用出场日及以前的最大 MFE）在顺延期间收盘创新高的极少数情况下会与引擎的 `mfe_R` 不同。若要与引擎完全一致，可在有信号后冻结 MFE。
- **不能事后补记信号**：信号日之后已有每日行时拒绝补记更早的信号（防止看了后面的行情再挑一根收盘）。owner 若当天收盘后没来得及声明，只能用下一个收盘作为信号行。
- **`跟踪期满` 出场原因**：信号原因只有失效位 / 移动止盈 / 论点作废 / 手动，`跟踪期满` 无法再被写入出场记录（与 §9「暂不使用」一致；schema §2.3 仍列着这个原因）。
