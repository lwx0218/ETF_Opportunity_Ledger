# 卡片台账存储 `src/ledger/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active
- Owner: Faye
- Last updated: 2026-10-01
- Source of truth: `docs/etf-card-schema-v1.md`（含 v1.1 补充 a–g）；`docs/etf-fixed-sources-v1.md` §3–§5；`operations/planning/2026-09-27-astra-execution.md`（A1–A4）；replan §3 P3、§8 P6b、§9 P6c-2、§10 P6d-2、§11 P7

## 用法

```bash
python -m src.ledger init      [--db data/ledger.sqlite]    # 建库并同步 docs/etf-fixed-sources-v1.csv
python -m src.ledger summary   [--db …]                     # 分母、分档、手动出场占比、校准分桶
```

代码里用 `src.ledger.store.Ledger`：`create_card(card, evidence, agent_score)` → `owner_score` → `enter` → `append_daily` → `exit` → `finalize`；`void` 作废。正式台账 `data/ledger.sqlite` 入 Git（replan §11）：`journal_mode = DELETE`，提交时不留 `-journal` / `-wal`；测试只许连临时库（`ETF_LEDGER_TESTING` 置位时连默认库即报错）。时间一律北京时间 `YYYY-MM-DDTHH:MM`，百分数存数值（12.5 = 12.5%）。卡片上的所有价格（失效位、进场、出场、每日收盘、止损）都在该卡的研究序列上，与信号同一口径；执行 ETF 的真实成交不在本层。

**数据库时钟**：触发器用 `ledger_now()`（`Ledger` 注册，北京时间到分钟，每个事务内冻结为同一时刻）判断截止与「不能写未来」；各表的 `recorded_at` 必须等于它。没注册这个函数的连接（sqlite3 命令行、别的进程）写不进台账行与固定源版本；自己注册同名函数等于注入时钟，属于蓄意绕过，存储层不防。注入时钟只用于回放：`Ledger(回放库, clock=…, replay=True)`，不能指向正式库；库第一次打开时记下时钟模式（`ledger_meta.clock` = real / replay），之后换模式打开即拒绝——回放写出的卡进不了正式台账。

**schema 版本**：`ledger_meta.schema` = `v1.1-h`（新库建库时写入；出场信号的五个边角，P6e-2）。之前版本建的库（P3 / P5 的回放库没有 `evidence_status` 等列；P6b 的 `v1.1` 库出场记录没有触发收盘；P6c 的 `v1.1-f` 库没有出场信号表；P6d 的 `v1.1-g` 库没有 `ew_daily` / `job_days`；P7 的 `v1.1-g.1` 库出场信号表没有 `seq`）打开即拒绝并提示迁移；正式台账按 A7 还没有启用，所以本包不提供迁移脚本，旧回放库删掉重跑即可。

## 字段落点（schema §2 → 表.列）

| schema 字段 | 落点 | 约束 |
|---|---|---|
| `id` | `cards.id` | `T-YYYY-NNN`，主键不复用 |
| `created_at` | `cards.created_at` + `cards.close_date` | 到分钟、日期必须真实存在；`close_date 15:00 ≤ created_at ≤ 其后第一个工作日 09:30`（不能看了后面的行情再补卡）；不晚于数据库时钟；数据库时钟过了 `owner_score_deadline` 也不能再立 |
| （扫描自然键） | `cards.scan_key` | 可空、唯一；P5 同一候选重跑不重复立卡 |
| `container` / `instrument` | `cards.container`；`instrument_code`、`instrument_name`、`research_index_code` | 非空（研究指数可空，如现金） |
| `trigger_type` / `state_at_entry` | `cards.trigger_type` / `cards.state_at_entry` | 枚举：三类触发；状态码 POP … NEUTRAL |
| `thesis` | `cards.thesis` | 1–80 字 |
| `evidence_status`（v1.1-a） | `cards.evidence_status` ∈ {未检索, 已检索无证据, 有证据} | 创建时锁死；与触发类型成对（CHECK）：形态突破 / 恐慌下轨 = `未检索`，事件驱动 = `已检索*`；`有证据` 封存前至少一条证据，其余两种不能写证据；`未检索` 不能写 agent 分 |
| `evidence[]` | `evidence` 表：schema 四字段 + `first_seen_at`、`available_at`、`snapshot_path`、`snapshot_sha256` + `source_grade`（写入时等级快照） | 只能与卡片同一事务写入；`source_id` 须在当前版本固定源清单且为 A / B 级（Python 层再对照一次 CSV）；`available_at`、`first_seen_at` ≤ `created_at`；`available_at ≥ published_at`；只有 `evidence_status = 有证据` 的卡能写 |
| `evidence_strength` | `strength_scores(card_id, rater ∈ {agent, owner}, score 0–5, reason, scored_at, recorded_at)` | A1 / v1.1-b：两栏各自锁定；agent 随卡片创建，`已检索*` 的卡封存前必须存在，`未检索`（机械卡）的卡没有 agent 行（为空，不是 0）；owner 只能在封存后写一次，截止按**数据库时钟**对 `cards.owner_score_deadline`（下一交易日 09:30，距信号日 ≤ 14 天：春节 / 国庆休市连周末最长约 11 天）判断，调用方给的时间不算数；缺失即无行 |
| `expectation` | `expectation_horizon_days`、`expectation_target_excess_pct`、`expectation_target_r`（v1.1-c）、`expectation_benchmark` | 基准 ∈ {等权组合, 沪深300}；与 `scoring_rule` 成对：菜单第 1 项必须有 horizon 与 target_excess、target_r 为空；菜单第 2 项只限形态突破 / 恐慌下轨，horizon 与 target_excess 为空、target_r = 2、基准 = 等权组合 |
| `invalidation` | `invalidation_price`、`invalidation_atr_value`、`invalidation_atr_multiple` | 均 > 0 |
| `r_unit` | `r_unit_per_share`、`r_unit_pct_of_nav` | > 0 |
| `planned_size_pct` | `cards.planned_size_pct` | 0 < x ≤ 25 |
| `scoring_rule` | `cards.scoring_rule` | 固定菜单两项：`schema-v1-§3`（按超额）、`schema-v1.1-R`（按 R 倍数，v1.1-c） |
| `tracking_days` | `cards.tracking_days` | 固定 20（A2） |
| `counterfactual` | `cf_ew_level`、`cf_hs300_level`、`cf_container_price` | 必填 |
| `crowding_at_entry` | `crowd_rs_1m_rank`、`crowd_rs_3m_rank`、`crowd_vol_ratio_20`、`crowd_premium_pct`、`crowd_share_chg_20d` | 可空（观测缺失） |
| A3 论点失效条件 | `thesis_inval_source_id`、`thesis_inval_deadline`、`thesis_inval_statement` | 事件驱动卡必填、其他卡必空；来源须 A / B 级 |
| `supersedes` | `cards.supersedes` | 只能引用已作废的卡，且新卡晚于作废时刻；一张旧卡只能被取代一次 |
| §2.2 每日行 | `daily` 表 | 按日期严格递增追加，不晚于数据库时钟；出场后继续追加到期满；作废或期满后拒绝 |
| 进场 | `entries` 表 | 成交不早于 `owner_score_deadline` 那次开盘（不能倒填；owner 打分时这笔交易还没发生；早盘确认的卡当天可进）、不晚于数据库时钟；进场价必须高于失效位（否则按「未进场而失效」作废）；只一次 |
| 出场信号（v1.1-g 第 3 条、v1.1-h） | `exit_signals(card_id, seq, signal_date, reason, manual_reason, signal_close, recorded_at)`，主键 `(card_id, seq)` | write-once，每张卡一条（`seq = 1`），先写为准；**唯一例外**（v1.1-h 第 4 条）：同一信号日已有 `失效位` / `移动止盈` 时，owner 可再记一条 `论点作废`（`seq = 2`），别的覆盖（反向、手动、不同信号日、第二次覆盖）一律拒绝。须已进场、未出场；信号日不早于进场日、不晚于数据库时钟；**信号日必须已有每日行，`signal_close` 等于它的收盘**（v1.1-g 第 1 条 (a)），信号日之后已有每日行时不能补记（v1.1-h 第 2 条）；`失效位` 信号的收盘必须低于锁定失效位（第 1 条 (b)）；**`失效位` / `移动止盈` 信号的收盘必须低于当时生效的止损**——前一行每日记录的 `stop_now`，没有前一行或它没记止损时用锁定失效位（v1.1-h 第 5 条；`移动止盈` 须已激活由每日任务保证）；`手动` 必须写 `manual_reason`；原因只有失效位 / 移动止盈 / 论点作废 / 手动（`跟踪期满` 保留在出场表的枚举里但不使用，v1.1-h 第 3 条）。止损信号由每日任务在跌破那天收盘后写；手动 / 论点作废由 owner 在某日收盘后声明（第 2 条）。`Ledger.exit_signal(cid, fill_date=D)` 返回在 D 开盘成交时生效的那条 |
| §2.3 出场 | `exits` 表 | 须先有进场；不晚于数据库时钟；`手动` 必须写 `manual_reason`；**必须有出场信号**，`exit_date` 晚于信号日（「之后第一个有开盘价的交易日成交、中间不撤销」由每日任务保证；台账不存开盘价，存储层只要求出场日晚于信号日），`exit_reason`、`manual_reason`、`exit_signal_close` 都必须等于**生效的**信号里的值（成交日 09:30 前记录的覆盖优先，否则第一条；v1.1-h 第 4 条）；`手动` / `论点作废` 信号必须在成交那天 09:30 之前记录（收盘后决定、次日开盘成交，v1.1-g 第 2 条；止损信号由每日任务写，补跑晚记不受限）；出场后不能再补出场日之前的每日行 |
| §2.4 跟踪期满 | `finals` 表 | 出场后的每日行满 `tracking_days` 行才能写；`final_score` 必须等于机械结果（触发器重算，v1.1-f）：先判证伪——`exit_signal_close` < 锁定的 `invalidation_price`（不论出场原因标签）或 `exit_reason = 论点作废`（哪怕 R > 0）；未证伪的卡按锁定菜单分档：第 1 项按 `realized_excess_pct` 对 `target_excess_pct`，第 2 项按 `realized_r`（含成本）：≥ 2 达标、> 0 部分、≤ 0 未达（没有 −1 下限） |
| 作废 | `voids` 表 | 只有未进场的候选能作废；已进场的卡按「论点作废 / 手动」出场 |
| 等权日收益（v1.1-e） | `ew_daily(date, ew_return, ew_level, n_containers, recorded_at)` | replan §11：原「库旁文件」`ew_daily.csv` 改为库内表，台账与它天然成对（文件丢失、截断、换成别的面板的文件这几种失配不再可能）。只追加，日期严格递增、不晚于数据库时钟；第一条点位 1、收益 0，之后点位 = 上一条点位 ×（1 + 当日收益）（触发器核对）；卡片的 `cf_ew_level` 取创建当日这一行。每日任务另核对卡片的 `cf_ew_level` 与表、以及表是否漏了上一交易日（防绕过触发器的改动与漏跑） |
| 已处理交易日 | `job_days(day, recorded_at)` | 取代 `data/jobs/processed-days.txt`：每日任务跑完一天（台账流程未被阻断）记一行，漏跑检查用；只追加 |

生命周期由视图 `card_status` 推出：作废 / 已结 / 过去 / 当下 / 候选。所有表拒绝 DELETE；除 `cards.sealed` 在创建事务内 0→1 外（封存触发器核对数据库时钟等于卡片的 `recorded_at` 且未过 `owner_score_deadline`：不能先插一批未封存的卡、看完行情只封存赢家；未封存的卡不进分母），所有表拒绝 UPDATE；每张表的插入触发器在同键行已存在时拒绝，`INSERT OR REPLACE` / `REPLACE INTO` 的隐式删除因此也改不了任何行；表都是 `WITHOUT ROWID`，显式写 rowid 的 REPLACE 直接报错；`Ledger` 连接另开 `recursive_triggers` 作第二道防线。数值列校验类型并拒绝无穷大（`typeof` + `abs(x) < 1e15`），日期与时刻做往返校验（`2026-02-31`、空格分隔一律拒绝）。

固定源清单按版本只追加：`source_loads` 记每次载入的 CSV sha256 与递增序号（写入须用数据库时钟），`current_sources` 视图取最后一个版本；清单变了（如 S2 把 C 升 B）就追加新版本，已写入证据的等级快照不变。

## 统计口径

- `summary()["denominator"]` = 全部已封存卡片，含作废、未进场与在途（schema §1、A4）；`terminal` = 已结 + 作废；`hit_rate_over_terminal` = 达标数 ÷ 终态卡数（作废计入分母）；`falsified_thesis_void_positive_r` = 论点作废而证伪、但 R > 0 的卡数（v1.1-f：判断错了、钱对了，单列）。
- `calibration(rater)`：只用 `已检索*` 的卡按事前 `evidence_strength` 分桶 0–1 / 2–3 / 4–5，`未检索` 的卡单独一桶（v1.1-a）；每桶 `n` = 终态卡（已结 + 作废），在途卡单列 `open` 不进 `n`；`enough = n ≥ 30`（§6.1）。agent 与 owner 各一条曲线。

## 边界与待决

1. 存储层能防误改与流程绕行，防不了拿到数据库文件后 `DROP TRIGGER` 的蓄意篡改。
2. 固定源 §3 的 B 级 `available_at` 已由 I-23 更正为取 min；存储层只强制 `available_at ≤ created_at`、`first_seen_at ≤ created_at`、`available_at ≥ published_at`，具体取值由写入方按规则算。
3. A1 双栏（v1.1-b）与证据时点字段（v1.1-d）已补进 schema v1.1。
4. 已进场的卡不能作废（否则亏损可以靠作废从 R 分布里消失），只能按「论点作废 / 手动」出场；已进场的卡要不要也能 `supersedes`，待 Cowork 定口径。
5. 「证伪」的判定已由 v1.1-f 统一（两项菜单）：按触发收盘对锁定失效位与论点作废判，不再用 `realized_r ≤ −1`。v1.1-g 起触发收盘 = 出场信号那一行每日记录的收盘，记信号时就要求那一行已存在——进场当天收盘后才能记第一条信号，所以不再有「出场前没有每日行」的卡。
