# P3 · 卡片存储 `src/ledger/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §3 P3——按 card schema v1 建 SQLite 存储，冻结字段在存储层强制
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Executor: Claude Code（云端）
- Route: direct-execute（Owner 指示按 replan §3 顺序推进）
- Source of truth: `docs/etf-card-schema-v1.md`；`docs/etf-fixed-sources-v1.md`；astra-execution A1–A4；replan §3 P3

## 结果

| 完成判据 | 结果 |
|---|---|
| schema 每个字段有落点 | 通过：`tests/ledger/test_ledger.py::SchemaCoverage` 逐字段核对表与列；对照表见 `docs/ledger-storage.md` |
| 改锁死字段必须失败 | 通过：`cards` 全部锁定列逐列 UPDATE 均被冻结触发器拒绝；`INSERT OR REPLACE` / `REPLACE INTO` 改写整张卡同样被拒，分母不变 |
| §2.5 每条禁令一个失败测试 | 通过：事后加证据、改证据、改 expectation / invalidation / scoring_rule / evidence_strength、删卡（含作废卡，含借 UNIQUE 冲突的隐式删除）、修正不走作废 + supersedes——每条都覆盖 UPDATE、DELETE、REPLACE 三种写法 |
| 作废流程 | 通过：只有候选能作废；作废 → 新卡 `supersedes`；未作废不能被取代；一张旧卡只能被取代一次；两张卡都计入分母 |
| 固定源校验 | 通过：不在清单 / C 级 / `available_at > created_at` / `first_seen_at > created_at` 均拒绝，整张卡回滚；固定源表按版本只追加 |
| 测试 | `python -m unittest discover -s tests -t .`：61 个全过（原 31 + 台账 30） |
| 包末复核 | 首轮 `return_to_planning`（F1 阻断）→ 已按下表逐条修复，复验见 PR |

## 复核发现与处理

| # | 发现 | 处理 |
|---|---|---|
| F1 阻断 | `INSERT OR REPLACE` 的隐式删除绕过全部冻结，能改卡、改结果、改 owner 分、让卡从分母消失；外键关闭时借 UNIQUE 冲突能物理删卡 | 每张只追加表加「同键行已存在即拒绝」的插入触发器（含 `scan_key`、`supersedes` 唯一列）；`Ledger` 连接另开 `recursive_triggers`；每张表补 REPLACE 失败测试 |
| F2 高 | 可倒填进场（晚立卡、用旧价格进场） | 进场日必须晚于卡片创建日、不晚于数据库时钟；数据库时钟过了下一次开盘就不能再立卡 |
| F3 高 | 作废已进场的卡后结果永远写不进去，亏损可消失 | 只有候选能作废；已进场只能按「论点作废 / 手动」出场 |
| F4 中高 | owner 栏截止与评分时刻由调用方传入 | 截止按数据库时钟 `ledger_now()` 判断；截止必须是 09:30、晚于信号日且 ≤ 10 天；各表 `recorded_at` 必须等于数据库时钟；裸连接写不进 |
| F5 中 | 数值列不校验类型（unicode 负号字符串让「达标」通过） | 所有数值列 `typeof` 检查 |
| F6 中 | calibration 把未结卡算进 n | n 只含终态卡（已结 + 作废），在途单列 |
| F7 中 | 固定源表可直接改 | 按版本只追加（`source_loads` + `current_sources`）；证据存等级快照；Python 层再对照 CSV |
| F8 中 | 日期只用 GLOB，`2026-02-31`、`2026-19-99`、空格分隔都能进 | 日期 / 时刻往返校验 |
| F9 低 | 重跑重复建卡；期满不查跟踪期；进场价低于失效位；tracking_days 未锁 20；recorded_at 时区不一 | `scan_key` 唯一；出场后满 20 行每日才能期满；进场价须高于失效位；`tracking_days` 固定 20；`recorded_at` 统一北京时间 |

「证伪」口径（失效位出场 vs realized_r ≤ −1）与已进场卡能否 supersedes，交 Cowork 定（见 `docs/ledger-storage.md`「边界与待决」）。

## 实现要点

- 冻结靠 SQLite 触发器，不靠 Python：卡片先以未封存写入，证据与 agent 评分写完后同一事务内封存；之后 `cards` 任何列都不能改，证据和 agent 评分不能再加。
- A1：`strength_scores` 两栏各自锁定，owner 截止按数据库时钟判定，缺失即无行。
- A3：事件驱动卡必须带论点失效条件（固定源 A / B 级 + 判定日 + 可证伪陈述）。
- `finals.final_score` 由触发器按 §3 规则从出场记录重算比对，写错档直接拒绝。

## 待决（交 Cowork）

1. fixed-sources §3 的 B 级 `available_at` 规则 max / min 与正文矛盾（详见 `docs/ledger-storage.md`「边界与待决」第 2 条）。
2. schema v1.1 补记 A1 双栏、证据时点字段、`scan_key`；确认「证伪」口径与已进场卡的修正方式。
