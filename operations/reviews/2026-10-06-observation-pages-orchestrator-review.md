# 真实观察双页：编排复核与退回项

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: Codex 双页交付独立复核，形成可复现修复范围
- Timestamp (UTC): 2026-10-06
- Owner: Faye
- Route: review-only
- Source of truth: AGENTS.md；operations/planning/2026-10-06-observation-and-pages.md；docs/project-intake/etf-opportunity-ledger.md；docs/etf-card-schema-v1.md
- Reviewed head: `2e72a884efa2b961ecc74af39e06cb54913abdd6`（业务提交 `43dcba8`）
- Base: `ae7b63d89967267bbb4d1f1cb0ea077fb86f56a7`
- Decision: return_to_planning（下述两项 P2 缺陷及一项产品验收欠项修复后复验；不合并、不部署本 head）

## 已确认的进展

真实观察读模型、首页与 `/rotation`、37 容器周矩阵、序列身份和字段资格已实现。原生价格、研究/执行/候选分开、三模式隔离以及严格 live 门均有代码与相称测试。与此前仅行情登记表相比，这次承接了首包主要结构；不能因以下退回而否认已完成部分，也不能提前认定完整产品完成。

三条只读复核分别检查观察数学/资格、原始产品要求与页面、live/API 隔离。live/API 未发现新增缺陷；观察和产品复核发现以下问题，编排又独立复现。未修改业务代码或正式数据。

## 必修 1 · P2：研究读数链接继承错误序列

定位：`src/web/static/app.js` 的 `route`、`observationLink`、`renderObservationHome`（约 136–138 行）和 `renderRotation`（约 164 行）。

`route` 继承现有查询，而首页研究收盘/RS 列、轮动行头和周格没有显式设 `series=research`。从

```text
/rotation?mode=market&as_of=2026-09-30&theme=T02&series=execution
```

点击 T01 的研究周格，实际函数生成

```text
/rotation?mode=market&as_of=2026-09-30&theme=T01&series=execution
```

编排直接运行当前 JS 路由函数复现该 URL；实际 HTTP 又确认：研究格是 `H00300`、RS=0，错误详情却是 `510300`、RS=null。首页研究读数也有同样问题。这不是后台混库，而是点击语义与详情身份不一致。

修复：明确展示研究读数的链接必须选择 research；纯跨页导航和用户明确选择序列的操作可以保留当前 series。回归覆盖 execution 和 price_candidate 两种起点，点击研究行头/周格/首页读数后，身份、日期、数值及刷新均一致。

## 必修 2 · P2：海外已确认断档恢复后丢失历史缺口

定位：`src/observation/metrics.py` 的 `calculate`（约 120–121、165–175 行）只检查末日 data_hole 和仍存在的原生行；`src/observation/model.py` 的详情图生成（约 203–213 行）同样未保留缺失整段。

可复现的纯内存案例：

```python
from tests.observation.test_model import ObservationTests
c = ObservationTests()
c.setUp()
try:
    c.add_container('T02', 'FOREIGN', 1, source='yahoo')
    c.seed('FOREIGN', 'yahoo', days=c.days[:130])
    for d in c.days[100:111]:
        c.con.execute("DELETE FROM bars WHERE code='FOREIGN' AND date=?", (str(d.date()),))
    result = c.observe(112, theme_id='T02')
finally:
    c.tearDown()
```

观察日 2022-06-08，已知中段触发过 data_hole，恢复首根日期为 06-07。当前返回 `state=XB / qualification=complete / reason=null`，`atr20=2.0 / reason=null`；RS 则正确因窗口缺口不可用。图表直接从 05-20 跳到 06-07，`gaps=[]`。

编排裁定本包的修复边界：保留截至观察日已确认的断档历史；不能让“今日恢复报价”证明“指标依赖历史完整”。EMA 依赖仍有确认缺失时，观察 state/ext 不给完整可用判定、不重置起点；ATR20 依赖窗口及前收跨确认缺口时不可用，直到所需连续真实输入齐备才恢复。图表对已确认缺口明确断段/说明，不补 OHLC、不把未知值填零。所有判断只用当日已经知道的断档事实，不将后来第 5 日确认倒灌到此前截面。

此修复限观察资格与展示，不改正式 I-25 状态/交易算法、策略参数或海外正常休市对齐。增加恢复首根、依赖窗口恢复、历史截断的合成回归；研究路径保持原合同。

## 必修 3 · 本包产品欠项：冻结详情直接回答触发与退出依据

定位：`src/web/static/app.js` 的 `renderDetail`（约 298–313 行）。当前显示论点、触发类别、失效价和目标，但没有呈现后端已有的冻结形态/拥挤快照、ATR 失效位依据和冻结评分规则；当前止损只在折叠的每日表中。

编排用隔离 demo 的半导体 `T-2026-004` 核实：API 已有 `state_at_entry=XB`、`crowd_rs_1m_rank=4`、失效价 129.6、ATR=2.15、倍数=2、`scoring_rule=schema-v1-§3`，最新每日行也有 `stop_now`。不是缺数据导致不能展示。

这是原有详情尚未按本包承诺补全的欠项，不是本次新增算法回归。请在价格图前用简洁结论回答“当时为何触发”“现在按什么条件退出”：只用已冻结字段及实际 daily/signal/exit，区分创建失效位、当前生效止损、论点失效与已提交待成交信号；非空的形态/拥挤依据和评分规则可展开查看，缺值不补造。不改变评分、交易或封存规则。

验收至少包含候选、持有、已有待成交信号、出场后四种状态；用户不应从一张长表自行拼出退出条件。

## 验证证据与限制

- 编排在 Python 3.12 / 当前 SQLite 环境运行全套 444 项：442 通过，2 项因新 worktree 尚无忽略的 `outputs/` 而在 TemporaryDirectory 前置失败。创建该运行目录后，仅重跑这两项，均通过；没有宣称第二次整套执行。该前置依赖在原测试中已存在，建议测试夹具自行建临时根，不作为本包新增产品缺陷。
- 独立 live/API 目标组 85 项亦在修正临时目录前置后全部通过；无越权或正式写入证据。
- 编排实际本地 HTTP 验证 `/`、`/rotation` 均 200，观察 API 有 37 容器，且分别读取 T01 research 与 execution，确认必修 1 的实际身份差异。
- 云端浏览器对本地预览返回 `net::ERR_BLOCKED_BY_CLIENT`。本轮没有独立浏览器/截图验收通过；Codex 的截图索引保存在其忽略 outputs，仓库只有记录。修复交付仍须提供绑定准确代码版本/启动模式的实际浏览器旅程和可读取截图证据。
- 真实读取范围：2026-09-30、T01 的研究/执行详情及返回的 37 容器单周观察；合成用例另列，不作真实研究结果。没有运行正式研究、真实 daily 或创建正式台账。
- 正式库 SHA256 核查前后为 `448c8f1f3a9568b7cde5ebcf8a4dc5eb8392ca59c9681cea938235430ef8d150`。

## 后续

Codex 在原任务分支修复上述三项，补针对性回归和实际浏览器旅程，按既有独立复核/Ponytail要求推送；编排复核后再合并。无需重写已正确的底座或扩为全部产品后包。

Pi 报告的 `7866f79` 尚未推送，本轮未看到其证据文件。摘要的 95 行异常、78 行旁证/17 行无旁证、单位 unverified 不等于异常已修复或量单位已核定。先将现有轻量证据提交推到独立远端分支，再核对；本轮不据摘要授权修库、解除字段限制或重跑取证。
