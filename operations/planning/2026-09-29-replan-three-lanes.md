# 重新规划 · 三条线并行（Claude Code 建底座，Cowork 验证策略，astra 服务器补全）

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 取代 `2026-09-27-orchestration-input.md` §B 的 round 切分；R0 收口；后续任务按执行者分包
- Timestamp (UTC): 2026-09-29
- Owner: Faye（分工原则由她定：CC 建底座并最小化验证数据源；Cowork 负责规划、产品设计、策略有效性验证；astra 在服务器上补全与全量重算）
- Route: plan
- Source of truth: AGENTS.md；docs/etf-rotation-prereg-v1.md；docs/etf-card-schema-v1.md；docs/etf-fixed-sources-v1.md；operations/planning/2026-09-27-prereg-v1-implementation-notes.md；operations/planning/2026-09-27-astra-execution.md（A1–A7、C 已由 Owner 口头批准）

> A1–A7 与 C 的决定不变。V1 实现口径（I-01 ~ I-19）不变。改的是**谁做、按什么顺序、用什么证据标准**。

## 0. 为什么重排

R0 在服务器上跑了两天（09-27 → 09-29），39 个主题保留 0、剔除 0、pending 39，没有 `data/universe.csv`，没有代码。原因不在 astra 不努力，而在两处：一是 R0 的完成判据（我在 orchestration 输入里写的「两源交叉 + 60 日成交额 + 历史起点 + 收益口径」）把研究级证据标准套在了查表任务上；二是「历史起点」「收益口径」只有把序列拉下来才知道，R0 在等 R1 才能给的答案。此外每个阶段都走「写 → 独立复核 → 重算哈希 → 百行日志」，四轮复核结论都是「approve / 仍 incomplete」，没有人问离交付还差什么。

处理：**R0 由 Cowork 直接做决策收口**（见 §1），astra 的 R0 证据作为参考保留；后续按执行者分三条线并行，不再串行等服务器。

## 1. R0 收口：`data/universe.csv` v1（2026-09-29）

39 个主题的决定已写入 `data/universe.csv`：**保留 31、带问题保留 6、剔除 1（保险：无纯保险 ETF 可执行）、只作执行不进面板 1（现金）**。进面板的容器 37 个；独立方向仍按 prereg 的估计 8–12 个。

字段：`research_index_code`（研究序列）、`research_route`（从哪条路拉：csi / eastmoney_index / eastmoney_etf_hfq / yahoo / eia_or_yahoo）、`tr_code_candidates`（全收益版本候选代码，由 probe 逐个试）、`execution_fund_code`（执行 ETF，首选）、`execution_alternatives`、`status`、`open_question`。

指数身份来自 astra R0 的核验（34 项有原文资料）；4 处配对错误已按其发现修正（半导体改 512480、白酒研究指数改中证酒 399987、纳指科技用 NDXTMC、纳指100 / 标普500 注明价格 vs 总收益）。

**非单一指数容器的口径（Claude 决定，理由附）：**

| 容器 | 研究序列 | 执行 | 理由 |
|---|---|---|---|
| 黄金 | 518880 后复权（2013-07 起）；若能拉到上海金 Au99.99 日线则替换 | 518880 | 黄金 ETF 持实物金，跟踪误差可忽略，研究=执行不引入偏差；上海金历史更长但免费源不确定 |
| 原油 | 布伦特（EIA RBRTE 日现货，或 BZ=F 期货），美元 | 501018 / 160723 / 161129 | 没有中证指数；执行基金是 FOF 且带溢价，溢价按 prereg §3.3 只作执行层限制 |
| 国债 | H11077 的财富（含利息再投资）版本；拉不到则 511260 后复权 | 511260 | V1 要求含分红/利息再投资（I-18） |
| 现金 | 无 | 511880 / 511360 | 不出信号，是无持仓时的默认去处（prereg §5） |

「核实」的定义从此改为：**能从固定行情源拉到该代码的序列，起止日期与 factsheet 名称一致**。这由 CC 的 probe 完成（§3 P1），比逐条引文绑定更可靠，也更便宜。拉不到的容器标记后跳过，不阻塞其他容器。

## 2. 分工原则

| 谁 | 做什么 | 判断标准 |
|---|---|---|
| **Claude Code（CC）** | 全部底座代码 + 数据源可用性的最小验证 + 文档对齐 PR | 能在仓库里以代码 + 测试交付的，都归 CC；先让 CC 干 |
| **Cowork（Claude）** | 规划、产品设计、研究文档、**策略有效性验证（V1）**、对 CC 指标实现的研究逻辑复核 | 需要研究判断或设计判断的 |
| **astra（服务器）** | 用 CC 的代码做全量回填与重算、需要国内网络的核实、定时任务与长期运行 | 只有服务器能做的：出网到国内数据源、7×24 运行、全量重算 |
| **Faye** | 推送（cc）、合并 PR、把数据包带进 Cowork、A 类取舍 | — |

**不再让 astra 做的事**：R0 逐项核验、逐日逐基金抓成交额、写「暴露台账」、每阶段独立复核。

## 3. Claude Code 任务包（按顺序，每包一个 PR，Faye 合并）

前提：CC 云端环境的网络白名单需要加上行情源域名（`www.csindex.com.cn`、`oss-ch.csindex.com.cn`、`web.ifzq.gtimg.cn`、`push2his.eastmoney.com`、`query1.finance.yahoo.com`、`stooq.com`、`www.eia.gov`）。加不上也不阻塞：CC 仍写代码和测试，probe / backfill 由 astra 在服务器跑（§4 S1）。

### P1 · 数据层 `src/data/`（原 R1 的代码部分）

- **目标**：按 `data/universe.csv` 拉研究序列与执行 ETF 日线，能全量回填、能增量更新、能导出研究数据包。
- **参考实现**：`lwx0218/serenity_quant_research`（physical-first 分支）`api/app/ingest/{http,quotes,symbols,runner}.py`——标准库 HTTP + 统一 UA / 超时 / 重试；东财 K 线按 120 天分段（服务器上长窗口会断连）、Yahoo、stooq 三条路依次退；抓不到记 `ingest_todo`。**复制其模式与代码片段即可，不要把 serenity 作为依赖**（本项目去 serenity 化）。
- **路由**：`csi`（中证 `csindex-home/perf/index-perf?indexCode=&startDate=&endDate=`，按年分段；09-27 已验证 HTTP 200）、`eastmoney_index`（secid `1.xxxxxx` 沪 / `0.xxxxxx` 深，`klt=101`）、`eastmoney_etf_hfq`（同接口 `fqt=2` 后复权，用于研究=执行的容器）、`tencent`（`web.ifzq.gtimg.cn/appstock/app/fqkline/get`，单次 400 行，注意其 qfq 是减法复权，只用不复权或作交叉核对）、`yahoo` / `stooq`（海外指数）、`eia`（RBRTE 日现货 CSV）。
- **全收益版本**：对每个 `tr_code_candidates` 逐个试（H0xxxx、code+`CNY010`、H2xxxx），第一个返回数据且名称含「全收益 / 财富 / Total Return」的即采用；都没有则用价格指数并在 coverage 里标 `price_only`（V1 报告按 §2.3 每年 1% 打折并注明）。
- **命令**：
  - `python -m src.data probe`：对 universe 每一行试路由，输出 `outputs/data/coverage.csv`（container, code, route_used, first_date, last_date, rows, tr_code_used, price_only, error）。**这就是「数据源可用性的最小验证」**，也是 R0「核实」的最终形式。
  - `python -m src.data backfill --end 2026-09-30`：全量到 `data/raw/<code>.csv`（不入 Git）。
  - `python -m src.data update`：增量（往回多拉 10 天覆盖修正）。
  - `python -m src.data package --end 2026-09-30`：导出 `outputs/research-package-<end>/`（raw + MANIFEST sha256 + coverage）。
- **验证**：单元测试用录制的响应（fixtures）测解析与分段；probe 在 CC 环境实跑一次（能出网时）；与仓库 `data/kline_*.csv`（09-14 腾讯快照）重叠区间逐日比对，差异逐条解释。
- **完成判据**：coverage.csv 里 37 个面板容器每个有 `route_used` 或明确 `error`；拉不到的不阻塞；MANIFEST 可复验。

### P2 · 指标层 `src/indicators/`（原 R3）

- **目标**：从 `src/rotation/etf_probe.py` 的 `kell_states` 抽出状态机，字段 `kell` → `state`；ATR20（真实波幅 20 日简单均值，见 `src/research/prereg_v1/panel.py: reference_atr`）；`rs_1m` = 21 日收益 − H00300 的 21 日收益；`z_month`（只在每月最后一个交易日有值，用前 20 个已完成月末）。
- **输出**：implementation-notes §B 的长表（date, container, open, high, low, close, state, rs_1m, atr20, z_month）+ `bench.csv`（date, hs300 = H00300）。命令 `python -m src.indicators build --package outputs/research-package-<end>/`。
- **验证**：在 09-25 数据快照上重算，与 `data/panel_daily.csv` 一致（仅字段名不同）——这是既有产物，可精确对比；测试证明每个指标只用 t 日及以前的数据（截断测试，做法见 `tests/research/test_prereg_v1.py::test_no_lookahead`）；`python -m src.research.prereg_v1.run check` 能通过。
- **完成判据**：与历史产物一致；无未来函数；Cowork 对状态机移植做一次研究逻辑复核（读 diff，不重写）。

### P3 · 卡片存储 `src/ledger/`（原 R2）

- **目标**：按 `docs/etf-card-schema-v1.md` 建 SQLite 存储；创建时锁死的字段在存储层强制不可改（触发器拒绝 UPDATE / DELETE）；作废 + `supersedes`；作废卡计入分母的统计查询。`evidence[]` 每条增加 `first_seen_at`、`available_at`、`snapshot_path`、`snapshot_sha256`（fixed-sources §4），存储层校验 `source_id` 在 `docs/etf-fixed-sources-v1.csv` 且等级为 A / B，拒绝 `available_at > created_at`。
- **A1 对齐**：`evidence_strength` 改为两栏（agent、owner）各自锁定；owner 栏可空（次日开盘前未填记缺失）。这是 schema 的实现层扩展，不改 schema 文档正文；Cowork 之后在 schema v1.1 里补记。
- **验证**：改锁死字段必须失败的测试；§2.5 每条禁令一个失败测试；作废流程测试。
- **完成判据**：schema 每个字段有落点；测试全绿。

### P4 · 文档对齐 PR（A6）

- 把 astra-execution.md 记录的 A1–A7 / C 决定填进 `operations/planning/2026-09-27-orchestration-input.md` 的「决定」栏；intake §4.1「权威版本在 claude.ai Project」改为「仓库 docs/」；`AGENTS.md` PROJECT:OWNED 里「初始化时尚未导入」「任务 0–7 尚未开始」「§10 五项均未决」三句改为当前状态；framework §8 加一句指向 `docs/etf-fixed-sources-v1.md`。
- 治理层文件（AGENTS.md）由 Owner 通过 PR 修改属于合同允许的路径，不是产品 round 顺手改。

### P5 · 每日任务骨架 `src/jobs/`（原 R4 的代码部分，触发规则留空位）

- **目标**：收盘后流程的骨架：`update` → `build` → 触发候选卡（规则模块可插拔，V1 结果出来前只接「恐慌下轨」和「事件驱动」两类，A7）→ 更新在场卡每日行 → 检查失效位与移动止盈 → 出场写入 → 跟踪期统计。幂等：同一天重跑结果不变。
- **验证**：用历史数据回放若干天做冒烟（只验流程）；不产出任何研究结论。
- 定时与无人值守运行交 astra（§4 S3）。

P1 → P2 是关键路径；P3、P4 可并行；P5 在 P2、P3 之后。

## 4. astra 任务包（服务器）

- **S1 · 全量回填与研究数据包**（P1 合并后）：`probe` → `backfill --end 2026-09-30` → `package`；把 `outputs/research-package-2026-09-30/`（含 MANIFEST）交给 Faye 带进 Cowork。拉不到的容器在 coverage 里标明后跳过，**不逐条补证、不写暴露台账**。目标一次会话完成。
- **S2 · 固定信息源 C 级核实**（可与 S1 并行）：`docs/etf-fixed-sources-v1.md` §7 的 17 个 C 级 + 6 个待补时刻的 B 级，每个只核三项（官方页能否打开、发布时刻、存档入口），结果写回 `docs/etf-fixed-sources-v1.csv` 的等级与核实状态列，一行一个来源，不另写日志。
- **S3 · 定时与长期运行**（P5 合并、V1 出结果后）：`update` 与每日任务的 cron；连续 5 个真实交易日无人值守。
- **S4 · 同指数 ETF 的规模 / 成交额复核**（低优先级）：只对 `universe.csv` 里 `open_question` 写了「按规模复核」的容器，用交易所名录的规模字段先筛，规模前两名相差不到两倍才比 60 日成交额（用 09-27 已验证的接口，批量取）。
- **停止**：R0 的进一步核验、逐日逐基金请求、每阶段独立复核。已有 `outputs/r0/` 证据保留作参考；建议把 `outputs/r0/universe-candidates.csv` 与 `field-evidence.csv` 两个小文件提交到 `operations/r0/` 供以后追溯（可选）。

## 5. Cowork 任务

- **现在**：本文件；`data/universe.csv` v1；prereg §13.0 指针；给 CC 的任务包（即 §3）。
- **P2 合并后**：状态机移植的研究逻辑复核（只读）。
- **拿到研究数据包后**：V1，一次会话内 `check → characterize → design → oos → rolling`，结果追加 prereg §13，工作日志一页；A7 分支由结果决定，不通过时按 orchestration §A7 列的两个选项请 Faye 二选一。
- **之后**：R5 三态首页的方向稿（画布画板，浅深两版），产品设计；schema v1.1（A1 双栏、证据时点字段）。

## 6. 工作规则（三条线共用）

1. **证据标准按任务类型分级。** 工程 / 查表任务：URL + 获取日期 + 文件哈希即可。研究计算（收益序列的统计、回测、刻画）：完整研究纪律。「诚实登记已看过什么」只针对收益序列的计算结果，不针对产品页上看到的净值、规模。
2. **复核在包末做一次**，对着完成判据；reviewer 必须回答「这个交付能不能直接进下游」。中途不做哈希复核。
3. **日志每包一页**：结果表在最前，证据放 `outputs/`，失败写一行。
4. **拿得到就拿，拿不到先跳过**：任何数据源失败只记一行 `error`，不重试超过一次、不换协议、不猜接口；容器缺数据 → 面板里没有它，V1 报告注明。
5. **预注册已回答的问题，不再问 Owner**：研究池 = 指数、执行池 = ETF（prereg §2.1）；先定指数再选基金；QDII 溢价不进信号（§3.3）；无信号持现金（§5）；不加仓、不做空、不加杠杆；离场三条（§4）；新自由度只有 4 个（§7）。
6. **需要 Owner 判断的只有**：她的时间投入、偏好取舍、A7 不通过时的分支。技术口径由 Cowork 决定并附理由。

## 7. 里程碑

| 里程碑 | 内容 | 谁 | 判据 |
|---|---|---|---|
| M0 | 本计划 + universe.csv 合入 main | Faye 推送 | GitHub main 含本文件 |
| M1 | P1 + P2 合并；coverage.csv 出来 | CC | 37 个面板容器每个有路由或明确 error |
| M2 | 研究数据包（截至 2026-09-30） | astra 或 CC | MANIFEST 可复验，`run check` 通过 |
| M3 | V1 结论写入 prereg §13 | Cowork | 五条验收逐条通过 / 不通过 |
| M4 | 台账每日任务上线（按 A7） | CC 代码 + astra 运行 | 连续 5 个交易日无人值守 |
| M5 | 首页方向稿 → 实现 | Cowork 稿、CC 实现 | design-rules v3；无「如何使用」页 |
