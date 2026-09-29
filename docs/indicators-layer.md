# 指标层 `src/indicators/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active（只在构造数据上验证；真实数据包到达后跑 `legacy-check` 与 `run check`）
- Owner: Faye
- Last updated: 2026-09-29
- Source of truth: replan §3 P2、§8 P6a；implementation-notes E 节 I-20、I-21；`operations/planning/2026-09-27-prereg-v1-implementation-notes.md`（I-02、I-18、B 节）；`docs/etf-rotation-framework-v0.md` §3.1

## 用法

```bash
python -m src.indicators build --package outputs/research-package-2026-09-30/     # → outputs/panel-2026-09-30/
python -m src.research.prereg_v1.run check --panel outputs/panel-2026-09-30/panel.csv --bench outputs/panel-2026-09-30/bench.csv
python -m src.indicators legacy-check [--data data/]      # 与 09-25 快照 data/panel_daily.csv 逐日比对（state、ext、rs_1m）
```

build 先按 MANIFEST 复验数据包，不通过就拒绝；基准必须是数据包里的 `H00300`（沪深300 全收益，I-18），缺了就拒绝，不用价格指数顶替。

## 输出

- `panel.csv`：`date, container, open, high, low, close, state, rs_1m, atr20, z_month`（implementation-notes §B）。`container` 为 universe 的主题名；全部容器在 A 股日历（H00300 交易日）上（I-20）。
- `bench.csv`：`date, hs300, hs300_open`（H00300 收盘与原始开盘；开盘缺失时为空，不用收盘补。`hs300_open` 供每日任务的基准窗口「开盘到开盘」用，schema v1.1-e；V1 只读 `hs300`）。
- `build-report.json`：数据包 MANIFEST 的 sha256；每个容器的原始行数与对齐后行数、起止、路由、`price_only`、`volume_source`、各状态天数（可达状态表）、`z_month` 个数、补值 / 扩高低计数、原始无成交量行数、`volume_zero_after_align`（对齐后成交量为 0 的行，含平盘）、`calendar`（`a_share` / `overseas_d_minus_1`）；A 股路由另有 `dropped_off_calendar` / `missing_on_calendar`，海外路由另有 `stale_days` / `multi_bar_days` / `trailing_stale_days` / `last_bar_date`；跳过的容器与原因。

## 口径

| 列 | 定义 | 依据 |
|---|---|---|
| `state` | `src/rotation/etf_probe.py` 的 `kell_states` 原样移植，字段 `kell` → `state`；EMA10/20、SMA50、ATR14、20 日均量 | framework §3.1；移植逐日一致由测试在构造数据上证明 |
| `atr20` | 真实波幅的 20 日简单均值 | I-02；与 `prereg_v1.panel.reference_atr` 同一算法 |
| `rs_1m` | 容器 21 日收益 − 基准 21 日收益；基准取容器交易日当天或之前最近的收盘 | B 节；容器与基准同日历时与 `etf_probe.build_panel` 相同 |
| `z_month` | 仅在每月最后一个交易日有值：(月末收盘 − 前 20 个已完成月末收盘均值) / 其样本标准差 | B 节；与 `src/research/characterize.py` 同口径 |

- **月末判定**：下一行在新月份即为月末。最后一行：数据包里有交易日历 `calendar/sse-trading-days.csv`（schema v1.1-e）且覆盖到它之后时，看日历里的下一个交易日是否进入新月份，节假日跨月也能当天认出；没有日历或日历没覆盖到时，看下一个工作日是否进入新月份（月末落在周末当天能认出；月底最后一个工作日恰逢节假日的少数月份，要等下一行出现后才被认作月末）。两种情况下停更的序列都不会在月中冒出 z。`build-report.json` 的 `calendar_file` 记日历文件的 sha256（没有则为 null）；日历文件格式不对时 `build` 拒绝（见 `docs/data-layer.md`）。
- **只用过去**：全部指标只用 t 日及以前的数据；截断测试证明删掉 t 之后的数据，t 及以前每个值都不变。

## 日历对齐与成交量来源（I-20、I-21，implementation-notes E 节）

先对齐、再算指标；研究数据包（`build`）与每日任务（`src/jobs/live.py`）共用 `research_frame`，口径一致。

- **I-20 A 股日历**：全部容器对齐到 H00300 的交易日。A 股路由的容器，不在 A 股日历上的行丢弃（`dropped_off_calendar`）；自身首末日期之间日历上有而序列缺的交易日不补，只计数（`missing_on_calendar`，非零时日志打印），这几天该容器的收益在等权里缺席。海外路由（yahoo / stooq / eia）的容器，A 股交易日 D 取本地日期 ≤ D−1 的最后一根 K 线：美股、港股收盘都晚于 A 股 15:00，取 D−1 才没有未来视角；日股为统一口径也取 D−1。没有新 K 线时写平盘 K 线（开高低收 = 前收，成交量 0，`stale_days`）。两个 A 股交易日之间有多根新 K 线（A 股长假）时只用最后一根（`multi_bar_days`），跨假期收益落在这一根的收盘里。末尾连续平盘超过 3 行时日志警告，序列可能停更（`trailing_stale_days`，最后用到的 K 线日期 `last_bar_date`）；每日任务在 D 日末尾有平盘时也写进报告（停更不再表现为缺行）。对齐后海外容器的收盘序列在 A 股日历上没有空洞，A 股容器只在 `missing_on_calendar` 非零时有空洞；等权基准不再丢跨假期收益。
- **I-20 的折扣**：海外容器的研究序列比可执行的 QDII ETF 滞后一个交易日，V1 报告对海外容器单列并注明（数据陷阱第 5 条）。
- **I-21 成交量**：研究序列缺成交量的行超过一半时，按日期换成同一指数价格版本（coverage 的 `code` 对应的原始文件）的成交量，`volume_source = price_version`；借不到的保持原样（`none`：研究序列就是价格版本本身、价格版本文件不存在或也没有成交量）——`none` 只表示没借到，序列自带的少量成交量照用，放量四态能不能出现以 `states` 为准；自带成交量的（`self`）不动。状态机阈值一个不改。
- **平盘对 ATR 与均量的影响**（照 I-20 字面实现的结果，未调参）：平盘日真实波幅为 0、成交量为 0，会压低海外容器的 ATR20（失效位 = 2 × ATR20 因而偏紧，R 倍数被放大）与 20 日均量（下一天的放量门槛相对变低）。影响天数见 `stale_days`；V1 报告对海外容器的折扣说明需一并写明。

## 数据修整（非零计数打印到日志，并写进 build-report）

- 开 / 高 / 低缺失或非正时用收盘补。EIA 布伦特只有收盘价，ATR 因此退化为收盘到收盘的波幅。
- 高 / 低没有包住开收时，把高低价扩到包住开收（与 `build_hfq.py` 对腾讯两位小数高低价的处理相同）。
- 收盘缺失的行丢弃、重复日期保留最后一行，分别计数；**收盘非正直接报错**（P1 从不请求减法前复权，出现非正价就是数据坏了）。

## 已知局限

1. **可达状态**：没有成交量的行（`volume_source = none` 的容器中无量的行，如 EIA 布伦特；以及平盘日）放量条件恒为假；整条序列无量时启动 / 超跌反弹 / 过热 / 破位四态不可达；`build-report.json` 每个容器的 `states` 即可达状态表，V1 报告附上。
2. **与历史产物一致**：`legacy-check` 需在有 `data/kline_*.csv` 与 `data/panel_daily.csv` 的机器上跑一次。它验证的是函数移植，不经过日历对齐与 `load_series`。
3. **研究逻辑复核**：Cowork 已于 2026-09-29 复核通过（replan §8）。
