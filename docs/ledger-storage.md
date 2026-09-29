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

代码里用 `src.ledger.store.Ledger`：`create_card(card, evidence, agent_score)` → `owner_score` → `enter` → `append_daily` → `exit` → `finalize`；`void` 作废。数据库文件不入 Git。时间一律北京时间 `YYYY-MM-DDTHH:MM`，百分数存数值（12.5 = 12.5%）。卡片上的所有价格（失效位、进场、出场、每日收盘、止损）都在该卡的研究序列上，与信号同一口径；执行 ETF 的真实成交不在本层。

**数据库时钟**：触发器用 `ledger_now()`（`Ledger` 注册，北京时间到分钟，每个事务内冻结为同一时刻）判断截止与「不能写未来」；各表的 `recorded_at` 必须等于它。没注册这个函数的连接（sqlite3 命令行、别的进程）写不进台账行与固定源版本；自己注册同名函数等于注入时钟，属于蓄意绕过，存储层不防。注入时钟只用于回放：`Ledger(回放库, clock=…, replay=True)`，不能指向正式库；库第一次打开时记下时钟模式（`ledger_meta.clock` = real / replay），之后换模式打开即拒绝——回放写出的卡进不了正式台账。

## 字段落点（schema §2 → 表.列）

| schema 字段 | 落点 | 约束 |
|---|---|---|
| `id` | `cards.id` | `T-YYYY-NNN`，主键不复用 |
| `created_at` | `cards.created_at` + `cards.close_date` | 到分钟、日期必须真实存在；`close_date 15:00 ≤ created_at ≤ 其后第一个工作日 09:30`（不能看了后面的行情再补卡）；不晚于数据库时钟；数据库时钟过了 `owner_score_deadline` 也不能再立 |
| （扫描自然键） | `cards.scan_key` | 可空、唯一；P5 同一候选重跑不重复立卡 |
| `container` / `instrument` | `cards.container`；`instrument_code`、`instrument_name`、`research_index_code` | 非空（研究指数可空，如现金） |
| `trigger_type` / `state_at_entry` | `cards.trigger_type` / `cards.state_at_entry` | 枚举：三类触发；状态码 POP … NEUTRAL |
| `thesis` | `cards.thesis` | 1–80 字 |
| `evidence[]` | `evidence` 表：schema 四字段 + `first_seen_at`、`available_at`、`snapshot_path`、`snapshot_sha256` + `source_grade`（写入时等级快照） | 只能与卡片同一事务写入；`source_id` 须在当前版本固定源清单且为 A / B 级（Python 层再对照一次 CSV）；`available_at`、`first_seen_at` ≤ `created_at`；`available_at ≥ published_at`；空数组合法 |
| `evidence_strength` | `strength_scores(card_id, rater ∈ {agent, owner}, score 0–5, reason, scored_at, recorded_at)` | A1：两栏各自锁定；agent 随卡片创建、封存前必须存在；owner 只能在封存后写一次，截止按**数据库时钟**对 `cards.owner_score_deadline`（下一交易日 09:30，距信号日 ≤ 10 天）判断，调用方给的时间不算数；缺失即无行 |
| `expectation` | `expectation_horizon_days`、`expectation_target_excess_pct`、`expectation_benchmark` | 基准 ∈ {等权组合, 沪深300} |
| `invalidation` | `invalidation_price`、`invalidation_atr_value`、`invalidation_atr_multiple` | 均 > 0 |
| `r_unit` | `r_unit_per_share`、`r_unit_pct_of_nav` | > 0 |
| `planned_size_pct` | `cards.planned_size_pct` | 0 < x ≤ 25 |
| `scoring_rule` | `cards.scoring_rule` | 固定菜单，目前只有 `schema-v1-§3` |
| `tracking_days` | `cards.tracking_days` | 固定 20（A2） |
| `counterfactual` | `cf_ew_level`、`cf_hs300_level`、`cf_container_price` | 必填 |
| `crowding_at_entry` | `crowd_rs_1m_rank`、`crowd_rs_3m_rank`、`crowd_vol_ratio_20`、`crowd_premium_pct`、`crowd_share_chg_20d` | 可空（观测缺失） |
| A3 论点失效条件 | `thesis_inval_source_id`、`thesis_inval_deadline`、`thesis_inval_statement` | 事件驱动卡必填、其他卡必空；来源须 A / B 级 |
| `supersedes` | `cards.supersedes` | 只能引用已作废的卡，且新卡晚于作废时刻；一张旧卡只能被取代一次 |
| §2.2 每日行 | `daily` 表 | 按日期严格递增追加，不晚于数据库时钟；出场后继续追加到期满；作废或期满后拒绝 |
| 进场 | `entries` 表 | 成交不早于 `owner_score_deadline` 那次开盘（不能倒填；owner 打分时这笔交易还没发生；早盘确认的卡当天可进）、不晚于数据库时钟；进场价必须高于失效位（否则按「未进场而失效」作废）；只一次 |
| §2.3 出场 | `exits` 表 | 须先有进场；不晚于数据库时钟；`手动` 必须写 `manual_reason` |
| §2.4 跟踪期满 | `finals` 表 | 出场后的每日行满 `tracking_days` 行才能写；`final_score` 必须等于 §3 机械结果（触发器按 `exits` 与锁定的 `target_excess_pct` 重算） |
| 作废 | `voids` 表 | 只有未进场的候选能作废；已进场的卡按「论点作废 / 手动」出场 |

生命周期由视图 `card_status` 推出：作废 / 已结 / 过去 / 当下 / 候选。所有表拒绝 DELETE；除 `cards.sealed` 在创建事务内 0→1 外，所有表拒绝 UPDATE；每张表的插入触发器在同键行已存在时拒绝，`INSERT OR REPLACE` / `REPLACE INTO` 的隐式删除因此也改不了任何行；表都是 `WITHOUT ROWID`，显式写 rowid 的 REPLACE 直接报错；`Ledger` 连接另开 `recursive_triggers` 作第二道防线。数值列校验类型并拒绝无穷大（`typeof` + `abs(x) < 1e15`），日期与时刻做往返校验（`2026-02-31`、空格分隔一律拒绝）。

固定源清单按版本只追加：`source_loads` 记每次载入的 CSV sha256 与递增序号（写入须用数据库时钟），`current_sources` 视图取最后一个版本；清单变了（如 S2 把 C 升 B）就追加新版本，已写入证据的等级快照不变。

## 统计口径

- `summary()["denominator"]` = 全部已封存卡片，含作废、未进场与在途（schema §1、A4）；`terminal` = 已结 + 作废；`hit_rate_over_terminal` = 达标数 ÷ 终态卡数（作废计入分母）。
- `calibration(rater)`：按事前 `evidence_strength` 分桶 0–1 / 2–3 / 4–5；每桶 `n` = 终态卡（已结 + 作废），在途卡单列 `open` 不进 `n`；`enough = n ≥ 30`（§6.1）。agent 与 owner 各一条曲线。

## 边界与待决

1. 存储层能防误改与流程绕行，防不了拿到数据库文件后 `DROP TRIGGER` 的蓄意篡改。
2. 固定源 §3 的 B 级规则写的是 `available_at = max(发布日次日 00:00, first_seen_at)`，但正文又说「除非当天收盘前已抓到」——按 max 永远不能当天用，按 min 才符合正文。存储层只强制 `available_at ≤ created_at`、`first_seen_at ≤ created_at`、`available_at ≥ published_at`，具体取值由写入方按规则算；这处 max / min 待 Cowork 在 fixed-sources 里改清楚。
3. A1 双栏与证据时点字段是 schema 的实现层扩展，schema 正文未改；待 Cowork 在 schema v1.1 补记。
4. 已进场的卡不能作废（否则亏损可以靠作废从 R 分布里消失），只能按「论点作废 / 手动」出场；已进场的卡要不要也能 `supersedes`，待 Cowork 定口径。
5. 「证伪」按 `exit_reason = 失效位` 判定；手动出场即使 ≤ −1R 也按超额分档。schema §3 括注写的是「realized_r ≤ −1」，两者在手动 / 论点作废出场时不一致，待 Cowork 在 v1.1 确认。
