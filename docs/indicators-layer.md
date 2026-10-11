# 指标层 `src/indicators/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active（只在构造数据上验证；真实数据包到达后跑 `legacy-check` 与 `run check`）
- Owner: Faye
- Last updated: 2026-10-04（正式 build 接入只读研究输入预检）
- Source of truth: replan §3 P2、§8 P6a、§9 P6c-1、§10 P6d-1、§11 P7；implementation-notes E 节 I-20、I-21、I-24、I-25；`operations/planning/2026-09-27-prereg-v1-implementation-notes.md`（I-02、I-18、B 节）；`docs/etf-rotation-framework-v0.md` §3.1

## 用法

```bash
python -m src.indicators build --package outputs/research-package-2026-09-30.sqlite   # → outputs/panel-2026-09-30.sqlite
python -m src.indicators build --package <包.sqlite> --start YYYY-MM-DD   # 显式窗口；省略起点取官方日历首日
python -m src.research.prereg_v1.run check --panel outputs/panel-2026-09-30.sqlite     # --bench 默认同一个库
python -m src.indicators legacy-check [--data data/]      # 与 09-25 快照 data/panel_daily.csv 逐日比对（state、ext、rs_1m）
```

build 先用 `python -m src.data verify` 的同一套检查复验数据包（文件 sha256 对 MANIFEST、integrity_check、行数、截断、来源），不通过就拒绝；基准必须是数据包里的 `H00300`（沪深300 全收益，I-18），缺了就拒绝，不用价格指数顶替。

随后强制执行[研究输入预检](h00300-offline-restore.md)：请求窗口起点由 `--start` 声明或默认取官方日历首日，终点为包的 end；窗口超出官方日历可信范围即阻断，没有固定年份裁剪。预检和 build 共用窗口与原行情选择函数。基准每个交易日须有真实收盘，全部已声明研究容器须有真实 OHLC。缺收盘、缺 OHLC、缺容器均阻断，不自动选子集。`benchmark_ready` 与 `research_ready` 分列；基准可以只有收盘，T01 作为策略容器仍必须满足 OHLC 条件。海外须有早于窗口最后实际 A 股交易日的可用原生行，末日尚不可用的行单列，不让“只有末日行情”通过。失败打印质量 JSON 且不写面板；成功 `build-report.json` 保存 `input_quality`。

## 输出

一个库 `outputs/panel-D.sqlite`（`--out` 可换；不入 Git），旁边 `panel-D.build-report.json`。V1 用 `src/research/prereg_v1/panel.py` 的 `read_table(库, "panel" | "bench")` 读（NULL 读成 NaN）。

- `panel` 表：`date, container, open, high, low, close, state, rs_1m, atr20, z_month, data_hole`，主键 `(date, container)`，`data_hole` 只能是 0 / 1（implementation-notes §B）。`container` 为 universe 的主题名；全部容器在 A 股日历（H00300 交易日）上（I-20）。海外容器的 `high` / `low` 是该 A 股日所用那根 K 线的值（长假多根只取最后一根、平盘行 = 前收），**V1 不用**：引擎只用 `open`（次日成交）与 `close`（止损按收盘判），高低点只进指标，而指标在原生序列上算（I-24）。
- `bench` 表：`date, hs300, hs300_open`（H00300 收盘与原始开盘；开盘缺失时为空，不用收盘补。`hs300_open` 供每日任务的基准窗口「开盘到开盘」用，schema v1.1-e；V1 只读 `hs300`）。
- `meta` 表：`schema`（`panel-v1`）、`end`、数据包的 `content_sha256`，以及 JSON 格式的 `requested_window`、`trusted_calendar_range`、`effective_window`。不含生成时刻：相同数据包与相同窗口声明生成逐字节相同的面板库（同一 SQLite 版本）；显式和默认起点的声明差异保留在 meta。跨机器比对用内容哈希（`prereg_v1.panel.content_sha256`），V1 的 OOS 锁同时记文件与内容两个哈希。
- `build-report.json`：数据包文件的 sha256 与 `package_content_sha256`、源库 sha256 与打包时的 git commit、面板库的 sha256 与 `panel_content_sha256`、生成时刻、交易日历（`calendar`：天数与起止，没有则为 null）；每个容器的原始行数与对齐后行数、起止、路由、`price_only`、`volume_source`、各状态天数（可达状态表，只数非平盘行）、`z_month` 个数、补值 / 扩高低计数、原始无成交量行数、`volume_zero_after_align`（对齐后成交量为 0 的行，含平盘）、`calendar`（`a_share` / `overseas_d_minus_1`）；A 股路由另有 `dropped_off_calendar` / `missing_on_calendar`，海外路由另有 `stale_days` / `multi_bar_days` / `trailing_stale_days` / `last_bar_date`，以及 I-25 的 `max_stale_run`（中段最长连续平盘，不含末尾那段）、`stale_runs`（≥ 5 行的各段：`first`、`last`、`rows`、`trailing`、`hole_rows`）、`data_hole_rows`；跳过的容器与原因。

## 口径

| 列 | 定义 | 依据 |
|---|---|---|
| `state` | `src/rotation/etf_probe.py` 的 `kell_states` 原样移植，字段 `kell` → `state`；EMA10/20、SMA50、ATR14、20 日均量；**在容器原生 K 线上算**（I-24） | framework §3.1；移植逐日一致由测试在构造数据上证明 |
| `atr20` | 真实波幅的 20 日简单均值；**在容器原生 K 线上算**（I-24） | I-02；与 `prereg_v1.panel.reference_atr` 同一算法 |
| `rs_1m` | 容器 21 日收益 − 基准 21 日收益；基准取容器交易日当天或之前最近的收盘 | B 节；容器与基准同日历时与 `etf_probe.build_panel` 相同 |
| `z_month` | 仅在每月最后一个交易日有值：(月末收盘 − 前 20 个已完成月末收盘均值) / 其样本标准差 | B 节；与 `src/research/characterize.py` 同口径 |

- **月末判定**：下一行在新月份即为月末。最后一行：数据包的 `calendar` 表（schema v1.1-e）有日历且覆盖到它之后时，看日历里的下一个交易日是否进入新月份，节假日跨月也能当天认出；没有日历或日历没覆盖到时，看下一个工作日是否进入新月份（月末落在周末当天能认出；月底最后一个工作日恰逢节假日的少数月份，要等下一行出现后才被认作月末）。两种情况下停更的序列都不会在月中冒出 z。`build-report.json` 的 `calendar` 记日历的天数与起止（没有则为 null）；日历中间缺一段时 `build` 拒绝（见 `docs/data-layer.md`）。
- **只用过去**：全部指标只用 t 日及以前的数据；截断测试证明删掉 t 之后的数据，t 及以前每个值都不变。

## 日历对齐与成交量来源（I-20、I-21、I-24，implementation-notes E 节）

`research_frame` 的顺序：读取并截至消费窗口末日 → 借成交量（I-21）→ K 线级指标（I-24）→ 对齐 A 股日历（I-20）。研究数据包（`build`）与每日任务（`src/jobs/live.py`）共用它，口径一致；海外末日为 D−1 可用边界。量源选择比例也只使用当时已截至的数据，后来的成交量不得改变历史量源。

- **I-24 指标在原生序列上算、算完再对齐**：`state`（`form_states`，含 EMA / SMA / ATR14 / 20 日均量 / hi20 / lo20 / tight）与 `atr20` 按「该标的 20 根 K 线」算——海外容器用其本地交易日的原生 K 线，A 股容器先丢弃非日历行（那些行不是交易日）再算，结果与 P6a 完全相同。对齐时指标值随 K 线带到 D（同一条「本地日期 ≤ D−1 的最后一根」），平盘日沿用上一根的指标，**平盘 K 线不进指标**：真实波幅 0、成交量 0 不会压低 ATR20 与 20 日均量。长假多根 K 线不合并：假期内的高低点在原生序列上已进入 hi20 / lo20 / ATR。`rs_1m`、`z_month`、等权与引擎仍用对齐后的收盘 / 开盘。信息集不变（仍只用 ≤ D−1 的 K 线）。平盘日沿用上一根的状态可能让同一信号次日再出现一次，由 20 日冷却（I-05）与「已持有」检查挡住。
- **I-25 数据断档 `data_hole`**：连续 ≥ 5 个 A 股交易日没有新 K 线的平盘段是数据源断档，不是行情（真实休市最长 4 个交易日）。面板 `data_hole` 列（0 / 1，A 股容器恒 0）：连续平盘数到**第 5 行起**标 1。D 日只看 ≤ D 的行——那时还不知道这段平盘会不会延长，前 4 行与真实休市无法区分，按休市处理；这样截断测试仍逐行相等（I-25 已于 10-01 按此修订）。V1 在 `data_hole = 1` 的行上一律不做决策、也不作为别人的参照（I-26）：不产生入场信号（突破与恐慌都不，也不占 20 日冷却）；成交行是断档行时不入场，记 skipped「数据断档」、信号不保留（与「无开盘价」同一处理）；横截面排名前把断档行的 `rs_1m` 置空，不占名次也不进分母；设计期刻画按缺数据处理（不作样本、不作前向终点、不进当日等权）；零模型的随机入场池排除断档行。已持仓照引擎处理（平盘收盘记账，不会跌破止损）；出场的成交行是断档行时视同无开盘价，`exit_flag` 保留，顺延到第一个非断档行按其开盘成交（I-27）。`run check` 按整段列出断档（取 `panel-D.build-report.json` 的 `stale_runs`，注明第 5 行起挡），并核对面板的 `data_hole` 行数与报告一致；面板旁边没有报告时退回列出 `data_hole = 1` 的段并提示。`build` 日志对每段断档打印起止与行数。

- **I-20 A 股日历**：全部容器对齐到 H00300 的交易日。A 股路由的容器，不在 A 股日历上的行丢弃（`dropped_off_calendar`）；自身首末日期之间日历上有而序列缺的交易日不补，只计数（`missing_on_calendar`，非零时日志打印），这几天该容器的收益在等权里缺席。海外路由（yahoo / stooq / eia）的容器，A 股交易日 D 取本地日期 ≤ D−1 的最后一根 K 线：美股、港股收盘都晚于 A 股 15:00，取 D−1 才没有未来视角；日股为统一口径也取 D−1。没有新 K 线时写平盘 K 线（开高低收 = 前收，成交量 0，`stale_days`）。两个 A 股交易日之间有多根新 K 线（A 股长假）时只用最后一根（`multi_bar_days`），跨假期收益落在这一根的收盘里。末尾连续平盘超过 3 行时日志警告，序列可能停更（`trailing_stale_days`，最后用到的 K 线日期 `last_bar_date`）；每日任务在 D 日末尾有平盘时也写进报告（停更不再表现为缺行）。对齐后海外容器的收盘序列在 A 股日历上没有空洞，A 股容器只在 `missing_on_calendar` 非零时有空洞；等权基准不再丢跨假期收益。
- **I-20 的折扣**：海外容器的研究序列比可执行的 QDII ETF 滞后一个交易日，V1 报告对海外容器单列并注明（数据陷阱第 5 条）。
- **I-21 成交量**：研究序列缺成交量的行超过一半时，按日期换成同一指数价格版本（coverage 的 `code` 对应的原始文件）的成交量，`volume_source = price_version`；借不到的保持原样（`none`：研究序列就是价格版本本身、价格版本文件不存在或也没有成交量）——`none` 只表示没借到，序列自带的少量成交量照用，放量四态能不能出现以 `states` 为准；自带成交量的（`self`）不动。状态机阈值一个不改。

## 数据修整（非零计数打印到日志，并写进 build-report）

**正式 build 与 live 的覆盖规则（2026-10-06）**：两者均在只读快照内检查全池原始输入并以 strict 路径运行，不执行缺失/非正开高低的收盘填补；缺收盘、缺容器或缺日历直接阻断。A 股计算视图以官方 `calendar` 而非 H00300 已有日期为准，研究窗口外与非交易日原行情保留在库里。两者不适用上文「缺日只计数」「跳过容器」「缺日历退回工作日」的旧行为；海外 D−1、休市占位及 data_hole 保持原口径。旧的高低价扩包络研究政策仍保留，等待独立源证据裁定；本轮没有运行真实 build/live 或 P6g。

页面的 `src/observation` 是独立的只读字段资格视图：复用现有指标公式，但不扩包络、不补 OHL；真实收盘可独立展示与计算 RS，不代表策略研究就绪。状态资格需 70 根合格原生历史，ext 使用状态内部 ATR14，风险刻度使用 ATR20。日期、序列身份和具体缺口随每个字段返回；这不改变正式研究算法、参数或选择池。完整页面使用说明见 [可运行台账](runnable-ledger.md)。

- 开 / 高 / 低缺失或非正时用收盘补。EIA 布伦特只有收盘价，ATR 因此退化为收盘到收盘的波幅。
- 高 / 低没有包住开收时，把高低价扩到包住开收（与 `build_hfq.py` 对腾讯两位小数高低价的处理相同）。
- 收盘缺失的行丢弃、重复日期保留最后一行，分别计数；**收盘非正直接报错**（P1 从不请求减法前复权，出现非正价就是数据坏了）。

## 已知局限

1. **可达状态**：没有成交量的 K 线（`volume_source = none` 的容器中无量的行，如 EIA 布伦特）放量条件恒为假（平盘日不进指标，沿用上一根的状态）；整条序列无量时启动 / 超跌反弹 / 过热 / 破位四态不可达；`build-report.json` 每个容器的 `states` 即可达状态表（只数非平盘行：平盘日只是上一根状态的拷贝，I-25），V1 报告附上。
2. **与历史产物一致**：`legacy-check` 需在有 `data/kline_*.csv` 与 `data/panel_daily.csv` 的机器上跑一次。它验证的是函数移植，不经过日历对齐与 `load_series`。
3. **研究逻辑复核**：Cowork 已于 2026-09-29 复核通过（replan §8）；P6a / P6b 于 2026-09-30 复核通过（replan §9）。
