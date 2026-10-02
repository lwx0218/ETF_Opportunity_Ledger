# Cowork 复核 · CC 的 P7 / P6e-1 / P6e-2（main `ea87e8b`）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §11 P7、§12 P6e-1 / P6e-2 合并后的研究逻辑复核（只读；工程复核已由 CC 包末 reviewer 完成）
- Timestamp (UTC): 2026-10-02
- Owner: Faye
- Reviewer: Claude（Cowork）
- Route: review-only
- Source of truth: replan §11、§12；implementation-notes I-26；schema v1.1-h

## 结论

**通过。S1 可以开始；`build` 之前还要 G1（治理层一句）与 P6f-1（I-27，很小）。** 235 个测试本地全过。P7 是存储位置的变化，取数、指标、信号、引擎逻辑一行未动，复核用新旧两版在同一套假网络数据上端到端对拍逐位相同（`high / low / atr20` ≤ 1 ulp 的差来自旧版 CSV 浮点解析），这是我最在意的一条，成立。

## 逐包

| 包 | 核对点 | 结果 |
|---|---|---|
| P7 内容哈希 | `content_sha256` 逐表逐行规范化，不含作业时刻；同一源库、同一 D、同一 commit 跨机器相同；`verify` 核对；OOS 锁记面板内容哈希 | 通过。这比我在 §11 写的「包的 sha256」更对，已改 §11 措辞 |
| P7 只读打包 | `package` 只读打开源库，打包作业记在包内；源库 sha256 不变 | 通过。否则 Cowork 每次本地打包都会弄脏入 Git 的库 |
| P7 面板可复现 | 面板库不含生成时刻，同包两次 `build` 逐字节相同 | 通过 |
| P7 防线 | 测试只许连临时库，默认库路径在建文件之前拒绝；`bars` 拒绝 UPDATE 与换来源；旧 schema 拒绝 | 通过 |
| P7 Git | `.gitignore` 白名单只放行两个库、`universe.csv`、`events/`；提交节奏写明无热日志、`integrity_check = ok` | 通过；AGENTS.md 那一句由 G1 修订 |
| P6e-1 排名 | `rs_1m.where(data_hole == 0)` 后再排名，断档行既不占名次也不进分母 | 通过 |
| P6e-1 引擎 | 成交行断档记 skipped「数据断档」，信号不保留 | 通过；出场的同一情形由 I-27 / P6f-1 补 |
| P6e-1 刻画与零模型 | 断档行不作样本、不作前向终点、不进当日等权；零模型池与策略可入行同一集合 | 通过；副作用（每段断档前至多 20 个样本去掉）V1 报告注明 |
| P6e-1 `run check` | 按整段列断档并核对面板与 build-report，对不上非零退出 | 通过 |
| P6e-2 边角 | MFE / MAE 冻结；论点作废覆盖限成交日 09:30 前、别无覆盖；止损类信号收盘 < 生效止损；断档日候选卡作废；恐慌规则不看断档 | 通过 |
| P6e-2 顺带修复 | owner 09:30 后补记手动出场不再崩，顺延到下一开盘 | 通过；存储层时限由 v1.1-i 第 1 条收紧 |

## 留意项的去向

全部裁定于 replan §13：G1 治理层修订（Owner 批准）、I-27 + v1.1-i（P6f）、文档旧路径已改、其余接受。

## 已看过什么

只读代码、三份工作日志与构造数据的测试输出；没有接触真实行情，没有运行研究。
