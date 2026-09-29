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

- **月末判定**：下一行在新月份即为月末；数据的最后一行只有在数据包 `end` 覆盖到该月最后一个日历日时才算月末（不把「后面没数据」当成「后面没交易日」）。
- **只用过去**：全部指标只用 t 日及以前的数据；截断测试证明删掉 t 之后的数据，t 及以前每个值都不变。

## 数据修整（全部计数进 build-report）

- 开 / 高 / 低缺失或非正时用收盘补。EIA 布伦特只有收盘价，ATR 因此退化为收盘到收盘的波幅。
- 高 / 低不包住开收时收紧到开收范围（与 `build_hfq.py` 对腾讯两位小数高低价的处理相同）。
- 收盘缺失或非正的行丢弃。

## 已知局限（交 Cowork 判断）

1. **无成交量的序列**：状态机的放量条件（量 > 1.5 × 20 日均量）恒为假，启动 / 超跌反弹 / 过热 / 破位四态不会出现。全收益指数（H 开头、CNY010、^XNDX、^SP500TR）和 EIA 可能没有成交量；`build-report.json` 的 `volume_missing_or_zero` 与 coverage 的 `volume_missing_rows` 会显示。用哪条成交量（例如借价格版本的量）是研究口径，本层不自行决定。
2. **海外容器的交易日历**：纳指、标普、日经、恒生科技用各自交易所的日历，行里有 A 股休市的日子；V1 引擎怎么处理由 Cowork 确认。
3. **状态机移植的研究逻辑复核**：按 replan §3 P2，由 Cowork 读 diff 复核一次（只读，不重写）。
