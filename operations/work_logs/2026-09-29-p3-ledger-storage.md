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
| 改锁死字段必须失败 | 通过：`cards` 34 个锁定列逐列 UPDATE，均被冻结触发器拒绝（断言错误来自触发器而非 CHECK） |
| §2.5 每条禁令一个失败测试 | 通过：事后加证据、改证据、改 expectation / invalidation / scoring_rule / evidence_strength、删卡（含作废卡）、修正不走作废 + supersedes |
| 作废流程 | 通过：作废 → 新卡 `supersedes`；未作废不能被取代；一张旧卡只能被取代一次；两张卡都计入分母 |
| 固定源校验 | 通过：不在清单 / C 级 / `available_at > created_at` / `first_seen_at > created_at` 均拒绝，整张卡回滚 |
| 测试 | `python -m unittest discover -s tests -t .`：54 个全过（原 31 + 台账 23） |

## 实现要点

- 冻结靠 SQLite 触发器，不靠 Python：卡片先以未封存写入，证据与 agent 评分写完后同一事务内封存；之后 `cards` 任何列都不能改，证据和 agent 评分不能再加。
- A1：`strength_scores` 两栏各自锁定，owner 只能在 `owner_score_deadline`（创建时锁定的次日开盘时刻）前写一次，缺失即无行。
- A3：事件驱动卡必须带论点失效条件（固定源 A / B 级 + 判定日 + 可证伪陈述）。
- `finals.final_score` 由触发器按 §3 规则从出场记录重算比对，写错档直接拒绝。

## 待决（交 Cowork）

1. fixed-sources §3 的 B 级 `available_at` 规则 max / min 与正文矛盾（详见 `docs/ledger-storage.md`「边界与待决」第 2 条）。
2. schema v1.1 补记 A1 双栏与证据时点字段。
