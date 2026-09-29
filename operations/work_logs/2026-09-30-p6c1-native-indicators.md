# P6c-1 · K 线级指标在原生序列上算（I-24）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §9 P6c-1——`src/indicators/build.py` 实现 implementation-notes I-24（阻塞 V1）
- Timestamp (UTC): 2026-09-30
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示「先做 P6c-1，再做 P6c-2」）
- Source of truth: implementation-notes I-24；replan §9；main `4772cb7`

## 结果

| 项 | 结果 |
|---|---|
| 计算顺序 | `research_frame`：读取 → 借成交量（I-21）→ `bar_indicators`（`form_states` 的 `state` 与 `atr20`）→ 对齐（I-20）。海外容器在原生序列上算；A 股容器先丢非日历行再算 |
| 对齐带指标 | `align_to_calendar` 把指标列（`state`、`atr20`）随 K 线带到 D，其他非 K 线列不带；平盘行开高低收 = 前收、量 0，指标沿用上一行 |
| `container_panel` | 用带来的 `state` / `atr20`；缺这两列直接报错（不静默在对齐后的序列上重算、退回 P6a 口径），只有明确给原生序列时传 `compute_indicators=True`。`rs_1m` / `z_month` 不动 |
| 长假 K 线 | 不合并；面板里海外容器的 `high` / `low` 是最后一根的值，文档注明「V1 不用」 |
| 每日任务 | 共用 `research_frame`，自动跟上，`src/jobs/` 未改 |
| 测试 | `python -m unittest discover -s tests -t .`：176 个全过（新增 6 个，对应 §9 的 (a)–(e) 另加面板层一例）：(a) 平盘日 `state` / `atr20` = 上一行；(b) 每一行 = 本地日期 < D 的最后一根原生 K 线的指标，美股假日后第一根的 `atr20` 与原生相等、与 P6a 做法不等；(c) 春节中段只在美股 02-18 出现的高点使 02-23 的 BNB 不成立、ATR 变大，P6a 做法下有无该高点结果相同；(d) 3 个截断点：原始数据截到 D 之前（不含 D）、或把 D 及以后的价格 ×3 / 量 ×50，D 及以前的行都逐行相等；(e) A 股容器（含假期假行与缺日）与 P6a 结果逐列相同；(f) 面板里海外容器的 `state` / `atr20` 逐行等于原生值，缺指标列时报错。原有测试里直接传原生序列的 4 处调用改为显式 `compute_indicators=True`（另 1 处在新测试 (e) 里） |
| 文档 | `docs/indicators-layer.md`「日历对齐与成交量来源」加 I-24 一条、删去「平盘压低 ATR」一条；输出说明注明海外 `high` / `low` V1 不用；`build.py` 模块说明同步 |

## 包末复核

只读 reviewer 结论 `approve_with_follow_up`（顺序、指标带到 D、A 股与 P6a 逐项相同、无未来视角均用独立脚本与变异测试核过），4 条 non-blocking：

| # | 发现 | 处理 |
|---|---|---|
| 1 | 面板用带来的指标列这件事没有测试盯住：把 `container_panel` 改回在对齐后序列上重算（P6a 口径），40 个相关测试全过；缺列时的回退是静默通道 | 新增 (f) 面板层逐行对原生值（已用同一变异验证能抓到）；缺列改为报错，原生序列须显式 `compute_indicators=True` |
| 2 | 海外对齐多带出 `amount`、`source`，平盘行照抄上一根的 `amount` | 只带指标列 |
| 3 | (d) 截断在 `<= cut`，查不出「用了 D 当天 K 线」；日志把 3 个截断点写成「逐日」 | 改为截到 D 之前（不含 D），另加「D 及以后价格 ×3、量 ×50」不影响 D 及以前；日志改为「3 个截断点」 |
| 4 | 序列中段长断档时平盘行一路沿用断档前的状态（P6a 口径下同样给出可进态，不是本次回归）；报告只有总 `stale_days` 与末尾 `trailing_stale_days` | 未实现，交 Cowork（见下） |

## 交 Cowork 留意

- `build-report.json` 的 `states`（可达状态表）按面板行计数，海外容器的平盘日重复计上一根的状态。文档已写明，未改计数口径。
- **中段长断档**：海外序列中段断档（例如约 30 个 A 股交易日没有新 K 线）时，平盘行一路沿用断档前那根的状态与 ATR，可能在陈旧数据上连续给出可进态；I-24 的「20 日冷却挡住重复信号」只覆盖短的平盘段。`build-report` 目前只有总 `stale_days` 与末尾 `trailing_stale_days`，没有中段最长连续平盘。是否加一个中段最长连续平盘计数（例如 `max_stale_run`），或只在 V1 报告里注明，请 Cowork 定；本包未做。
