# 指标层 `src/indicators/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active（只在构造数据上验证；真实数据包到达后跑 `legacy-check` 与 `run check`）
- Owner: Faye
- Last updated: 2026-09-29
- Source of truth: replan §3 P2；`operations/planning/2026-09-27-prereg-v1-implementation-notes.md`（I-02、I-18、B 节）；`docs/etf-rotation-framework-v0.md` §3.1

## 用法

```bash
python -m src.indicators build --package outputs/research-package-2026-09-30/     # → outputs/panel-2026-09-30/
python -m src.research.prereg_v1.run check --panel outputs/panel-2026-09-30/panel.csv --bench outputs/panel-2026-09-30/bench.csv
python -m src.indicators legacy-check [--data data/]      # 与 09-25 快照 data/panel_daily.csv 逐日比对（state、ext、rs_1m）
```

build 先按 MANIFEST 复验数据包，不通过就拒绝；基准必须是数据包里的 `H00300`（沪深300 全收益，I-18），缺了就拒绝，不用价格指数顶替。

## 输出

- `panel.csv`：`date, container, open, high, low, close, state, rs_1m, atr20, z_month`（implementation-notes §B）。`container` 为 universe 的主题名；每个容器用自己的交易日。
- `bench.csv`：`date, hs300`（H00300 收盘）。
- `build-report.json`：数据包 MANIFEST 的 sha256、每个容器的行数、起止、路由、`price_only`、各状态天数、`z_month` 个数、补值 / 收紧计数、无成交量行数、不在基准交易日历上的天数；跳过的容器与原因。

## 口径

| 列 | 定义 | 依据 |
|---|---|---|
| `state` | `src/rotation/etf_probe.py` 的 `kell_states` 原样移植，字段 `kell` → `state`；EMA10/20、SMA50、ATR14、20 日均量 | framework §3.1；移植逐日一致由测试在构造数据上证明 |
| `atr20` | 真实波幅的 20 日简单均值 | I-02；与 `prereg_v1.panel.reference_atr` 同一算法 |
| `rs_1m` | 容器 21 日收益 − 基准 21 日收益；基准取容器交易日当天或之前最近的收盘 | B 节；容器与基准同日历时与 `etf_probe.build_panel` 相同 |
| `z_month` | 仅在每月最后一个交易日有值：(月末收盘 − 前 20 个已完成月末收盘均值) / 其样本标准差 | B 节；与 `src/research/characterize.py` 同口径 |

- **月末判定**：下一行在新月份即为月末；最后一行只有在其后的下一个工作日已进入新月份时才算月末（月末落在周末当天就能认出；停更的序列不会在月中冒出 z）。没有交易日历：月底最后一个工作日恰逢节假日的少数月份，最后一行要等下一行出现后才被认作月末。
- **只用过去**：全部指标只用 t 日及以前的数据；截断测试证明删掉 t 之后的数据，t 及以前每个值都不变。

## 数据修整（非零计数打印到日志，并写进 build-report）

- 开 / 高 / 低缺失或非正时用收盘补。EIA 布伦特只有收盘价，ATR 因此退化为收盘到收盘的波幅。
- 高 / 低没有包住开收时，把高低价扩到包住开收（与 `build_hfq.py` 对腾讯两位小数高低价的处理相同）。
- 收盘缺失的行丢弃、重复日期保留最后一行，分别计数；**收盘非正直接报错**（P1 从不请求减法前复权，出现非正价就是数据坏了）。

## 已知局限（交 Cowork 判断；第 1、2 条须在真实数据包到达、`characterize` 之前写进 implementation-notes）

1. **混合交易日历（V1 前必须定）**：每个容器用自己的交易日。只要面板里有一个海外容器，下游就会受影响（P2 复核在构造数据上实测）：
   - `prereg_v1.panel.ew_daily_returns` 在所有容器日期的并集上做 `pct_change(fill_method=None)`，A 股容器每段 A 股假期后第一天的收益、海外容器每个本地假日后的收益都被丢掉。11 年构造数据：等权累计 255%，按各自日历应为 283%。策略按最近收盘记账不丢这部分，所以对等权的比较（验收第 3、4 条）偏向策略。
   - A 股休市日只有海外容器参与 `rs_top_flags`，5 个海外容器时第 1 名就算「前 20%」。
   - 引擎会在 A 股休市日按海外价格成交或止损，而执行用的 QDII ETF 那几天停牌。
   - 前向收益与冷却期也按日期并集计数。

   两个方案二选一：
   - (a) 本层把所有容器对齐到 A 股（基准）日历，海外容器取「A 股收盘时已知」的最近值。注意美股 D 日收盘晚于 A 股 D 日收盘，需取 D−1；港股收盘也晚于 A 股。
   - (b) 改 prereg_v1，让等权收益、前向收益、排名都按各容器自己的日历计算。
2. **无成交量的序列（V1 前必须定）**：状态机的放量条件（量 > 1.5 × 20 日均量）恒为假，可进态「启动」和超跌反弹 / 过热 / 破位都不会出现，`characterize` 的「可进 vs 其余」会因此改变。全收益指数（H 开头、CNY010、^XNDX、^SP500TR）和 EIA 可能没有成交量，`build-report.json` 的 `volume_missing_or_zero` 与 coverage 的 `volume_missing_rows` 会显示。数据包已带价格版本的文件，可借它的成交量。用哪条成交量由 Cowork 定，本层再做一个小改动实现。
3. **与历史产物一致**：`legacy-check` 需在有 `data/kline_*.csv` 与 `data/panel_daily.csv` 的机器上跑一次。它验证的是函数移植，不经过 `load_series`。
4. **状态机移植的研究逻辑复核**：按 replan §3 P2，由 Cowork 读 diff 复核一次（只读，不重写）。
