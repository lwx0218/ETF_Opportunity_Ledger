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

## 8. 追加（2026-09-29 晚）· P1–P5 合并后的裁定与下一包

P1–P5 已合并（PR #1–#5，main `36b660f`，145 个测试通过）。CC 提出的问题裁定如下，细节见 `prereg-v1-implementation-notes.md` E 节（I-20 ~ I-23）与 `docs/etf-card-schema-v1.md` v1.1 补充：

| 问题 | 裁定 |
|---|---|
| 混合交易日历 | 对齐到 A 股日历；海外容器取本地日期 ≤ D−1 的最后一根 K 线，无新 K 线写平盘 K 线（I-20） |
| 全收益指数无成交量 | 借同一指数价格版本的成交量；都没有则四态不可达，报告注明（I-21） |
| NDXTMC 拉不到 | 不替代，T36 不进面板（I-22）；CC 的实现正确 |
| 固定源 B 级可用时点 | 取 min，文档与 CSV 已更正（I-23） |
| 恐慌卡「未检索证据」 | 新增 `evidence_status`，机械卡 = 未检索且**不写 agent 分**（不是 0）（v1.1-a） |
| 规则卡的量化预期 | 评分菜单第 2 项「R 倍数」，`expectation = {horizon_days: null, target_r: 2, benchmark: 等权组合}`（v1.1-c） |
| 骨架口径 | 全部确认，两处修改：基准窗口改为开盘到开盘；月末判定优先用交易日历文件（v1.1-e） |
| AGENTS.md「设计资产已导入」 | 接受，属实 |
| P5 开关 | 维持全部关闭直到 V1 结论（A7）；配置值先按 v1.1 写好但 `enabled: false` |
| P2 研究逻辑复核（Cowork） | **通过**：`form_states` 与 `etf_probe.kell_states` 逐条规则机械比对无差异（只有返回值的组装方式不同）；`rs_1m`、`z_month`、ATR20 与 prereg_v1 / characterize.py 同口径；截断测试覆盖无未来函数 |

### P6 · CC 下一包（P6a 阻塞 V1，先做；P6b 不阻塞）

- **P6a `src/indicators/build.py`**：实现 I-20（A 股日历对齐 + D−1 + 平盘 K 线 + `stale_days`）与 I-21（成交量借价格版本 + `volume_source` + 各状态计数）。测试：构造一个海外容器 + 一个 A 股容器，验证对齐后等权累计收益不再丢跨假期收益；截断测试照旧。
- **P6b `src/ledger/` + `src/jobs/`**：`evidence_status` 字段与封存规则（v1.1-a）；机械卡不写 agent 分；规则配置改为支持菜单第 2 项（`target_r`，`horizon_days` 可为 null）并加 `enabled` 开关；基准窗口开盘到开盘；交易日历文件读取（无文件时退回现规则）；等权日收益持久化。改完把 `TERMS_VERSION` 升到 `jobs-daily-v1`，Cowork 在配置里填 `confirmed_terms: jobs-daily-v1`。
- 每包仍是一页工作日志 + 包末一次复核。

### astra S1 补充

CC 的执行顺序与注意事项照办：`probe --record` → `backfill --end 2026-09-30` → `package` → `verify`，打包等北京时间 10-01 05:00 美股收盘后；限流时只动 `--exec-start`，不动 `--start`。另外两项：① 生成 `data/calendar/sse-trading-days.csv`（用 09-27 已验证的深交所 `monthList` 接口，覆盖 2005 至次年，一行一个交易日）并随数据包交付；② NDXTMC 若 probe 失败，试 Nasdaq 官方历史数据页一次，不成就跳过。

## 9. 追加（2026-09-30）· P6a / P6b 合并后的裁定与 P6c

P6a / P6b 已合并（PR #6、#7，main `7fba10a`，170 个测试通过）。两份工作日志「交 Cowork 留意」各条裁定如下，细节见 implementation-notes I-24 与 `docs/etf-card-schema-v1.md` v1.1-f。

| 留意项 | 裁定 |
|---|---|
| 平盘 K 线压低海外容器 ATR20 / 20 日均量 | **不接受折扣，改口径**：K 线级指标（`form_states`、ATR20）在容器原生序列上算、算完再对齐，平盘日沿用上一根的指标值（I-24）。理由：prereg 的 ATR20 指该标的 20 根 K 线，平盘 K 线只是横截面与引擎的占位，让它进指标才是静默改口径。V1 报告对海外容器仍单列 D−1 折扣（I-20 的折扣不变） |
| 长假多根 K 线只取最后一根 | **不合并**。引擎只用 open 与 close（止损按收盘判、次日开盘成交），高低点只有指标用，I-24 后指标已在原生序列上算，长假内高低点自然进入 hi20 / lo20 / ATR。面板里海外容器的 high / low 是最后一根的值，文档注明「V1 不用」 |
| 菜单第 2 项「证伪」两种读法 | **取失效位读法**（v1.1-f）：触发出场的那根收盘 < 锁定 `invalidation_price`，或论点作废；「未达」改为 `realized_r ≤ 0` |
| 菜单第 1 项「证伪」按失效位出场（P3 待决第 5 条） | **正确**，两项菜单统一为 v1.1-f；补上移动止盈 / 手动出场时收盘也跌破锁定失效位的情形 |
| 事件卡 `horizon_days` 只用于评分，离场只按止损 / 移动止盈 / 论点作废 | 接受；§2.3 的「跟踪期满」出场原因暂不使用 |
| 启用步骤（`confirmed_terms` + `enabled`） | 照办，仍待 V1 结论（A7）；P6c-2 之后版本号以 CC 升到的为准 |

### P6c · CC 下一包（P6c-1 阻塞 V1，先做；P6c-2 不阻塞）

- **P6c-1 `src/indicators/build.py`（I-24）**：`research_frame` 里把 `form_states` 与 `atr20` 的计算移到 `align_to_calendar` 之前（借量之后；A 股容器先丢非日历行再算）；`align_to_calendar` 把指标列随 K 线一起带到 D，平盘行沿用上一根的指标；`container_panel` 改用带来的列；`rs_1m` / `z_month` 不动。每日任务共用 `research_frame`，自然跟上。测试（构造海外序列）：(a) 平盘日的 `state` / `atr20` 等于上一根的值；(b) 美股假日后一天的 `atr20` 等于原生序列上该 K 线的 ATR20，与不对齐时逐根相等；(c) 长假内出现的最高价进入其后的 hi20（构造一个只在假期中段出现的高点，验证 BNB / tight 的判定用到了它）；(d) 截断测试仍逐行相等；(e) A 股容器结果与 P6a 完全相同。`docs/indicators-layer.md`「日历对齐与成交量来源」一节同步。
- **P6c-2 `src/ledger/` + `src/jobs/`（v1.1-f）**：出场记录加 write-once 字段记录触发出场的那根收盘；`mechanical_score` 与 `finals_insert` 触发器改为先判证伪（该收盘 < `cards.invalidation_price` 或 `exit_reason = 论点作废`），再按菜单分档，第 2 项「未达」= `realized_r ≤ 0`；旧回放库按 P6b 做法拒绝打开，不写迁移；`TERMS_VERSION` 升一版；`docs/jobs-daily.md` 同步。测试：失效位出场次日高开（−1 < R < 0）记证伪；移动止盈出场但收盘低于锁定失效位记证伪；论点作废且 R > 0 记证伪；未证伪但跳空致 R ≤ −1 记未达；菜单第 1 项同样四例。
- 每包仍是一页工作日志 + 包末一次复核；合并后 Cowork 做研究逻辑复核（只读）。

## 10. 追加（2026-10-01）· P6c 合并后的裁定与 P6d

P6c-1 / P6c-2 已合并（PR #8、#9，main `5c0ef8b`，183 个测试通过）。两份工作日志「交 Cowork 留意」裁定如下，细节见 implementation-notes I-25 与 `docs/etf-card-schema-v1.md` v1.1-g。

| 留意项 | 裁定 |
|---|---|
| P6c-2 存储层自加的两条核对（触发收盘 = 出场日之前最近一行的收盘、出场后不能补行；失效位出场的触发收盘必须低于失效位） | **接受**，写进 v1.1-g 第 1 条。手动出场同样用触发行收盘判证伪；出场一律次日开盘成交，没有盘中或当天收盘的出场时点 |
| 海外序列中段长断档，平盘行沿用陈旧状态 | **不只是注明，要标记并挡住开仓**（I-25）：连续 ≥ 5 个 A 股交易日没有新 K 线的平盘段 = 数据断档（真实休市最长 4 天），面板加 `data_hole` 列，V1 不在这些行上开新仓，已持仓照引擎处理；报告记 `max_stale_run` 与各断档段 |
| 可达状态表按面板行计数，平盘日重复计入 | 改为只按非平盘行计数（并入 P6d-1） |
| P5 遗留：止损次日无开盘价时出场顺延，若当天收盘回到止损之上信号丢失 | **按 V1 引擎修**（v1.1-g 第 3 条）：出场信号写 write-once 记录并持久化到成交，触发收盘改为信号行的收盘，第 1 条核对随之改为对信号行。不阻塞 V1，A7 之前无正式卡片、不迁移 |
| 远端 `-p6c1`、`-p6c2` 分支 | 删除；`claude/bold-archimedes-8mka2j*` 下其余已合并分支一并删除（先 `git branch -r --merged origin/main` 核对） |

### P6d · CC 下一包（P6d-1 很小但在 V1 之前落地；P6d-2 不阻塞）

- **P6d-1 `src/indicators/build.py` + `src/research/prereg_v1/{signals,run}.py` + `docs/indicators-layer.md`（I-25）**：`align_to_calendar` 对平盘段标 `data_hole`（连续 ≥ 5 行的中段或末尾平盘段整段为 1，≤ 4 行为 0），报告加 `max_stale_run`（中段最长连续平盘）与 `stale_runs`（≥ 5 的各段起止日期与行数）；`container_panel` 输出 `data_hole` 列（A 股容器恒 0）；`states` 可达状态表只按非平盘行计数。`signals.py` 的 `breakout_signals` 与 `panic_signals` 都排除 `data_hole = 1` 的行；`run.py check` 校验该列存在并打印各容器断档段；引擎不改。实现 `panel.py` 读取时若缺该列报错，不默认 0。测试：构造一段 30 行断档，断档内无信号、断档前后信号与无断档时相同；4 行休市段不标；末尾 ≥ 5 行标；已持仓的卡在断档内不出场、断档结束后第一根真 K 线按正常规则判；可达状态表不计平盘行；截断测试仍逐行相等。
- **P6d-2 `src/ledger/` + `src/jobs/`（v1.1-g 第 3 条）**：出场信号 write-once 记录（卡片、信号日、原因、信号日收盘），每日任务先处理未成交的信号，在第一个有开盘价的交易日成交，中间不撤销、不更新移动止盈；`exits` 引用信号，触发收盘 = 信号行收盘，核对 (a) 改为对信号行；`SCHEMA_VERSION` 与 `TERMS_VERSION` 各升一版，旧库拒绝、不迁移；`docs/ledger-storage.md`、`docs/jobs-daily.md` 同步。测试：止损次日无开盘价、第二天收盘回到止损之上，第三天仍出场且触发收盘是跌破那一行；顺延期间移动止盈不更新；手动与论点作废走同一条路径；与 V1 引擎用同一组构造数据比对出场日与价格。
- 每包仍是一页工作日志 + 包末一次复核；合并后 Cowork 做研究逻辑复核（只读）。
