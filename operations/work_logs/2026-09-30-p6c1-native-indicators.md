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
| 对齐带指标 | `align_to_calendar` 把 K 线以外的列随 K 线带到 D；平盘行开高低收 = 前收、量 0，指标沿用上一行 |
| `container_panel` | 用带来的 `state` / `atr20`；调用方直接给原生序列（没有这两列）时就地算。`rs_1m` / `z_month` 不动 |
| 长假 K 线 | 不合并；面板里海外容器的 `high` / `low` 是最后一根的值，文档注明「V1 不用」 |
| 每日任务 | 共用 `research_frame`，自动跟上，`src/jobs/` 未改 |
| 测试 | `python -m unittest discover -s tests -t .`：175 个全过（新增 5 个，对应 §9 的 (a)–(e)）：(a) 平盘日 `state` / `atr20` = 上一行；(b) 每一行 = 本地日期 < D 的最后一根原生 K 线的指标，美股假日后第一根的 `atr20` 与原生相等、与 P6a 做法不等；(c) 春节中段只在美股 02-18 出现的高点使 02-23 的 BNB 不成立、ATR 变大，P6a 做法下有无该高点结果相同；(d) 随机序列逐日截断逐行相等；(e) A 股容器（含假期假行与缺日）与 P6a 结果逐列相同。原有 170 个测试不改一行全过 |
| 文档 | `docs/indicators-layer.md`「日历对齐与成交量来源」加 I-24 一条、删去「平盘压低 ATR」一条；输出说明注明海外 `high` / `low` V1 不用；`build.py` 模块说明同步 |

## 交 Cowork 留意

- `build-report.json` 的 `states`（可达状态表）按面板行计数，海外容器的平盘日重复计上一根的状态。文档已写明，未改计数口径。
