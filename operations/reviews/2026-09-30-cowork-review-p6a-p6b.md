# Cowork 复核 · CC 的 P6a / P6b（main `7fba10a`）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §8 P6a / P6b 合并后的研究逻辑复核（只读；工程复核已由 CC 包末 reviewer 完成）
- Timestamp (UTC): 2026-09-30
- Owner: Faye
- Reviewer: Claude（Cowork）
- Route: review-only
- Source of truth: implementation-notes E 节 I-20 ~ I-23；docs/etf-card-schema-v1.md v1.1；replan §8

## 结论

**通过，附一个口径修正（I-24）与一个澄清（v1.1-f），由 P6c 落地。** 170 个测试在本地全过。两包都照裁定字面实现、没有擅自扩展，reviewer 提出的 14 条也都处理了。CC 交回来的四个留意项不是实现错误，是裁定本身留的口子，裁定见 replan §9。

## 逐包

| 包 | 核对点 | 结果 |
|---|---|---|
| P6a 日历对齐 | `searchsorted(side="left") − 1` 取的是本地日期 < D 的最后一根，即 ≤ D−1，无未来视角；无新 K 线写平盘（开高低收 = 前收、量 0）；多根只取最后一根并计数；A 股路由丢非日历行并计 `missing_on_calendar`；`last_bar_date` 让每日任务能发现停更 | 通过。平盘 K 线进指标的偏差（ATR20 低约 6%、放量门槛相对变低、`ext` 偏大）由 I-24 消除：指标改在原生序列上算、算完再对齐 |
| P6a 成交量借用 | 缺量 > 50% 才借；只借同一指数价格版本；`none` 只表示没借到；各状态计数进报告 | 通过 |
| P6b `evidence_status` | 创建时锁死；与 `trigger_type` 成对 CHECK（形态突破 / 恐慌下轨 = 未检索，事件驱动 = 已检索*）；未检索卡不能写 agent 分；校准分桶只用已检索 | 通过 |
| P6b 菜单第 2 项 | `scoring_rule = schema-v1.1-R` 与 `target_r` / `horizon_days = null` 成对约束；只限规则卡 | 通过。「证伪」按 `realized_r ≤ −1` 是对 v1.1-c 条件列的字面实现；v1.1-f 改为按锁定失效位判，P6c-2 改 |
| P6b 封存防倒填 | 封存触发器要求数据库时钟 = `recorded_at` 且未过截止：先插一批、过后只封存赢家的路被堵住 | 通过，这条比 P3 的口径更严，是对的 |
| P6b 基准窗口 | 沪深300 用 H00300 原始开盘价、进场日开盘到出场日开盘；缺开盘退回收盘口径；等权只有收盘点位总是退回 | 通过 |
| P6b 等权持久化 | 只追加；每天核对每张卡 `close_date` 的点位 = 冻结的 `cf_ew_level`；缺文件 / 末尾丢行 / 新库配旧文件即停 | 通过 |
| P6b 交易日历 | 文件在就校验（多列、周末、间隔 > 14 天报错），没有才退回工作日规则；`build` 与 `daily` 同一份 | 通过 |

## 已看过什么

只读代码、两份工作日志与构造数据的测试输出；没有接触真实行情，没有运行研究。
