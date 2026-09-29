# 卡片台账存储 `src/ledger/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active
- Owner: Faye
- Last updated: 2026-09-29
- Source of truth: `docs/etf-card-schema-v1.md`；`docs/etf-fixed-sources-v1.md` §3–§5；`operations/planning/2026-09-27-astra-execution.md`（A1–A4）；replan §3 P3

## 用法

```bash
python -m src.ledger init      [--db data/ledger.sqlite]    # 建库并同步 docs/etf-fixed-sources-v1.csv
python -m src.ledger summary   [--db …]                     # 分母、分档、手动出场占比、校准分桶
```

代码里用 `src.ledger.store.Ledger`：`create_card(card, evidence, agent_score)` → `owner_score` → `enter` → `append_daily` → `exit` → `finalize`；`void` 作废。数据库文件不入 Git。时间一律北京时间 `YYYY-MM-DDTHH:MM`，百分数存数值（12.5 = 12.5%）。

## 字段落点（schema §2 → 表.列）

| schema 字段 | 落点 | 约束 |
|---|---|---|
| `id` | `cards.id` | `T-YYYY-NNN`，主键不复用 |
| `created_at` | `cards.created_at` + `cards.close_date` | 到分钟；`created_at ≥ close_date 15:00` |
| `container` / `instrument` | `cards.container`；`instrument_code`、`instrument_name`、`research_index_code` | 非空（研究指数可空，如现金） |
| `trigger_type` / `state_at_entry` | `cards.trigger_type` / `cards.state_at_entry` | 枚举：三类触发；状态码 POP … NEUTRAL |
| `thesis` | `cards.thesis` | 1–80 字 |
| `evidence[]` | `evidence` 表：schema 四字段 + `first_seen_at`、`available_at`、`snapshot_path`、`snapshot_sha256` | 只能与卡片同一事务写入；`source_id` 须在固定源清单且为 A / B 级；`available_at`、`first_seen_at` ≤ `created_at`；`available_at ≥ published_at`；空数组合法 |
| `evidence_strength` | `strength_scores(card_id, rater ∈ {agent, owner}, score 0–5, reason, scored_at)` | A1：两栏各自锁定；agent 随卡片创建、封存前必须存在；owner 只能在封存后、`cards.owner_score_deadline`（次日开盘）前写一次，缺失即无行 |
| `expectation` | `expectation_horizon_days`、`expectation_target_excess_pct`、`expectation_benchmark` | 基准 ∈ {等权组合, 沪深300} |
| `invalidation` | `invalidation_price`、`invalidation_atr_value`、`invalidation_atr_multiple` | 均 > 0 |
| `r_unit` | `r_unit_per_share`、`r_unit_pct_of_nav` | > 0 |
| `planned_size_pct` | `cards.planned_size_pct` | 0 < x ≤ 25 |
| `scoring_rule` | `cards.scoring_rule` | 固定菜单，目前只有 `schema-v1-§3` |
| `tracking_days` | `cards.tracking_days` | 默认 20（A2） |
| `counterfactual` | `cf_ew_level`、`cf_hs300_level`、`cf_container_price` | 必填 |
| `crowding_at_entry` | `crowd_rs_1m_rank`、`crowd_rs_3m_rank`、`crowd_vol_ratio_20`、`crowd_premium_pct`、`crowd_share_chg_20d` | 可空（观测缺失） |
| A3 论点失效条件 | `thesis_inval_source_id`、`thesis_inval_deadline`、`thesis_inval_statement` | 事件驱动卡必填、其他卡必空；来源须 A / B 级 |
| `supersedes` | `cards.supersedes` | 只能引用已作废的卡，且新卡晚于作废时刻；一张旧卡只能被取代一次 |
| §2.2 每日行 | `daily` 表 | 按日期严格递增追加；作废或跟踪期满后拒绝 |
| 进场 | `entries` 表 | 成交日 > 信号收盘日；只一次 |
| §2.3 出场 | `exits` 表 | 须先有进场；`手动` 必须写 `manual_reason` |
| §2.4 跟踪期满 | `finals` 表 | `final_score` 必须等于 §3 机械结果（触发器按 `exits` 与锁定的 `target_excess_pct` 重算） |
| 作废 | `voids` 表 | 已出场的卡不能作废 |

生命周期由视图 `card_status` 推出：作废 / 已结 / 过去 / 当下 / 候选。所有表拒绝 DELETE；除 `cards.sealed` 在创建事务内 0→1 外，所有表拒绝 UPDATE。

## 统计口径

- `summary()["denominator"]` = 全部已封存卡片，含作废与未进场（schema §1、A4）；`hit_rate_over_all_cards` = 达标数 ÷ 分母。
- `calibration(rater)`：按事前 `evidence_strength` 分桶 0–1 / 2–3 / 4–5；每桶 `n` 含作废与未结卡，`enough = n ≥ 30`（§6.1）。agent 与 owner 各一条曲线。

## 边界与待决

1. 存储层能防误改与流程绕行，防不了拿到数据库文件后 `DROP TRIGGER` 的蓄意篡改。
2. 固定源 §3 的 B 级规则写的是 `available_at = max(发布日次日 00:00, first_seen_at)`，但正文又说「除非当天收盘前已抓到」——按 max 永远不能当天用，按 min 才符合正文。存储层只强制 `available_at ≤ created_at`、`first_seen_at ≤ created_at`、`available_at ≥ published_at`，具体取值由写入方按规则算；这处 max / min 待 Cowork 在 fixed-sources 里改清楚。
3. A1 双栏与证据时点字段是 schema 的实现层扩展，schema 正文未改；待 Cowork 在 schema v1.1 补记。
4. 作废当下（已进场）的卡：存储层允许（只要未出场），持仓如何处理由 P5 每日任务决定。
