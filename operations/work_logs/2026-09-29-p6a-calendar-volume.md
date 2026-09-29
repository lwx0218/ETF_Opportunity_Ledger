# P6a · 日历对齐（I-20）与成交量来源（I-21）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §8 P6a——`src/indicators/build.py` 实现 I-20、I-21（阻塞 V1）
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示「读 replan §8，做 P6a 再 P6b」）
- Source of truth: implementation-notes E 节 I-20、I-21；replan §8；本分支基于 Cowork 裁定提交 34b19fe

## 结果

| 项 | 结果 |
|---|---|
| I-20 A 股日历对齐 | 全部容器对齐到 H00300 交易日。A 股路由丢弃不在日历上的行（`dropped_off_calendar`）；海外路由（yahoo / stooq / eia）在 A 股交易日 D 取本地日期 ≤ D−1 的最后一根 K 线，无新 K 线写平盘（开高低收 = 前收，量 0，`stale_days`），长假期间多根新 K 线只用最后一根（`multi_bar_days`），末尾连续平盘 > 3 行告警（`trailing_stale_days`） |
| I-21 成交量来源 | 研究序列缺量行 > 50% 时按日期换成价格版本（coverage `code` 的原始文件）的成交量；`volume_source` ∈ self / price_version / none；各状态天数即可达状态表 |
| 共用路径 | 研究数据包 `build` 与每日任务 `src/jobs/live.py` 共用 `research_frame`，口径一致 |
| 测试 | `python -m unittest discover -s tests -t .`：152 个全过（新增 7 个）：D−1 取数与平盘、长假并入最后一根、A 股行丢弃、末尾平盘计数、对齐后无收益空洞（旧做法有）且等权日收益 = 当日均值、成交量三种来源、带对齐的截断测试 |

## 随之调整

- 每日任务默认日期改为「A 股已收盘的最近日期」，运行时间改为北京 15:30 之后。I-20 后海外容器在 D 日用 D−1 的 K 线，北京 D 日凌晨已收盘，不必再等次晨（`src/jobs/__main__.py`、`docs/jobs-daily.md`）。
- `docs/indicators-layer.md` 的「已知局限」1、2 已落地，改写为「日历对齐与成交量来源」一节。

## 交 Cowork 留意（照裁定字面实现，未擅自扩展）

- A 股长假期间海外有多根新 K 线时，按 I-20 字面只取最后一根：收盘正确（跨假期收益落在其中），但开 / 高 / 低只是最后一天的，假期内的高低点不进 ATR 与状态机。若要改为合并这几根（开 = 第一根开，高 / 低取极值，量求和），需改 I-20 的写法；`multi_bar_days` 给出影响天数。
