# Cowork 复核 · CC 的 P1–P5（main `36b660f`）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §3 P1–P5 合并后的研究逻辑复核（只读；工程复核已由 CC 包末 reviewer 完成）
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Reviewer: Claude（Cowork）
- Route: review-only
- Source of truth: replan §3、§8；implementation-notes I-01 ~ I-23；docs/etf-card-schema-v1.md（含 v1.1）

## 结论

**通过，可以在此基础上做 P6 与 S1。** 145 个测试在本地全过。研究纪律相关的关键点逐条核对如下；发现的都是 probe 才能证实的接口细节或已在 v1.1 里安排的改动，没有阻塞项。

## 逐包

| 包 | 核对点 | 结果 |
|---|---|---|
| P1 数据层 | 从不请求腾讯 qfq；只收已收盘 K 线（A 股 15:30 北京、海外 17:00 纽约）；全收益版本按名称含「全收益 / 财富 / TR」才采用；声明的替代只有 H11077 → 511260 后复权；NDXTMC 拉不到只探测 ^NDXT 不采用（与 I-22 一致）；`--exec-start` 只缩执行 ETF；请求日志与 MANIFEST 可复验；`package` 要求 A 股与海外都收盘 | 通过 |
| P2 指标层 | `form_states` 与 `etf_probe.kell_states` 逐条规则机械比对无差异（仅返回值组装不同）；ATR20 = 真实波幅 20 日简单均值（I-02）；`rs_1m` 基准只看当天或之前；`z_month` 与 characterize.py 同口径；183 个截断点无未来函数 | 通过；I-20 / I-21 由 P6a 实现 |
| P3 卡片存储 | 冻结字段靠触发器 + `WITHOUT ROWID`（挡住 REPLACE）；作废不删；`supersedes` 链；证据 `available_at`、`first_seen_at` 不得晚于 `created_at`；来源须为清单 A / B 级；创建时刻必须在收盘后、下一开盘前；owner 截止 09:30 | 通过；v1.1 需改：`expectation_horizon_days` 允许 NULL、`scoring_rule` 加第 2 项、加 `evidence_status`、未检索卡免 agent 分即可封存（P6b） |
| P4 文档对齐 | 决定栏、intake §4.1、AGENTS 三句 + 「设计资产已导入」、framework §8 指向固定源 | 通过 |
| P5 每日任务 | 时序与 V1 引擎一致（上一收盘信号 → 次日开盘成交；先离场后进场）；作废原因顺序与引擎一致；`scan_key` 幂等；漏跑守卫；触发规则全部关闭直到 V1 | 通过；机械卡 agent 分 0 → 改为不写分（v1.1-a，P6b） |

## 需要 probe / S1 证实的接口细节（不改代码，先跑再说）

1. 恒生科技的 Yahoo 符号写的是 `HSTECH.HK`；Yahoo 上指数更可能是 `^HSTECH`。probe 失败时先换这个符号再判「不可得」。
2. `^NDXTMC` 在 Yahoo 大概率不存在，按 I-22 处理。
3. EIA 路由需要服务器设 `EIA_API_KEY`（免费注册）；没有则退到 Yahoo `BZ=F`（2007-07 起，期货连续合约）。两者不拼接，选定后写进 coverage。
4. 中证 API 按年分段，每段约 245 行；若接口有单次行数上限，`_hole` 会把截断误判为中断，probe 的 `notes` 会显示。
5. 海外路由的收盘判定统一按纽约 17:00，日经 / 港股会晚半天进 raw；在 I-20 的 D−1 规则下没有影响。

## 已看过什么

只读代码与构造数据的测试输出；没有接触真实行情，没有运行研究。
