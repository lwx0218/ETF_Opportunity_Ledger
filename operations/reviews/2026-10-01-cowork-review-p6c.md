# Cowork 复核 · CC 的 P6c-1 / P6c-2（main `5c0ef8b`）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §9 P6c-1 / P6c-2 合并后的研究逻辑复核（只读；工程复核已由 CC 包末 reviewer 完成）
- Timestamp (UTC): 2026-10-01
- Owner: Faye
- Reviewer: Claude（Cowork）
- Route: review-only
- Source of truth: implementation-notes I-24；docs/etf-card-schema-v1.md v1.1-f；replan §9

## 结论

**通过。P6c-1 解除了 V1 的阻塞；再加一个很小的 P6d-1（I-25 数据断档标记）就可以 `build`。** 183 个测试在本地全过。两包都照裁定字面实现；CC 自己加的两条存储层核对是对的，已写进 v1.1-g。

## 逐包

| 包 | 核对点 | 结果 |
|---|---|---|
| P6c-1 计算顺序 | `research_frame`：读取 → 借量 → `bar_indicators`（`form_states` 的 `state` 与 ATR20）→ 对齐；海外容器在原生序列上算，A 股容器先丢非日历行再算 | 通过，与 I-24 字面一致 |
| P6c-1 对齐带指标 | `align_to_calendar` 只带 `INDICATOR_COLUMNS`，平盘行拷贝上一行的指标，不带 `amount` / `source` | 通过 |
| P6c-1 不静默回退 | `container_panel` 缺 `state` / `atr20` 直接报错，原生序列须显式 `compute_indicators=True`；面板层测试 (f) 用「改回 P6a 口径」的变异验证能抓到 | 通过，这条比我在 §9 要求的更严，是对的 |
| P6c-1 无未来视角 | 截断测试改为截到 D 之前（不含 D），并把 D 及以后的价格 ×3、量 ×50，D 及以前逐行相等 | 通过 |
| P6c-1 长假高低点 | 测试 (c)：只在春节中段美股出现的高点使节后 BNB 不成立、ATR 变大；P6a 口径下有无该高点结果相同 | 通过，正是 I-24 要的效果 |
| P6c-2 证伪判定 | 先判证伪（`exit_signal_close` < 锁定失效位，或论点作废），未证伪按菜单分档，第 2 项「未达」= R ≤ 0；穷举 396 张卡触发器与 `mechanical_score` 一致；收盘恰好等于失效位不算证伪 | 通过 |
| P6c-2 自加核对 | 触发收盘 = 出场日之前最近一行的收盘、出场后不能补行；失效位出场的触发收盘必须低于失效位 | 接受，写进 v1.1-g；P6d-2 之后「最近一行」改为「信号行」 |
| P6c-2 统计 | `falsified_thesis_void_positive_r` 单列「论点作废但 R > 0」 | 通过 |

## 留意项的去向

四条留意项全部裁定于 replan §10：两条核对接受；中段断档改为标记并挡住开仓（I-25，P6d-1）；可达状态表只按非平盘行计数（P6d-1）；顺延出场丢失按 V1 引擎修（v1.1-g 第 3 条，P6d-2）。

## 已看过什么

只读代码、两份工作日志与构造数据的测试输出；没有接触真实行情，没有运行研究。
