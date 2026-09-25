# 导入轮动面板、机会首页原型与研究资产

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 导入 QTradeResearch 权威文档、轮动面板与机会首页原型、研究脚本与设计参考资产
- Timestamp (UTC): 2026-09-25T11:35:22Z
- Owner: Faye
- Route: direct-execute
- Source of truth: AGENTS.md；README「从这里接手」第 2 步；Owner 2026-09-25 指示「把当下完成的轮动和首页的部分做一个 bundle，我去做一次提交」

## Goal / Summary

把 2026-09-14 至 09-19 在 claude.ai（Cowork 沙盒）里完成的东西原样搬进仓库，并让它们在仓库里可复现：权威文档进 `docs/`，生成脚本进 `src/`，两个界面原型的快照进 `prototypes/`，行情数据作为不入 Git 的快照随附。**这是资产导入，不是 intake 任务 0–7 的开始**；没有新的研究、取数或回测。

## Scope / Changes

```text
docs/
  etf-card-schema-v1.md              先读这个
  etf-rotation-framework-v0.md
  etf-rotation-prereg-v1.md
  etf-characterization-z.md
  etf-dividend-enhancement-prereg.md
  etf-dividend-bet-plan-v0.md        intake §4.1 之外的第 9 份：被 prereg-v1 引用，一并导入
  etf-l1-retrospective.md
  etf-thesis-log.md
  etf-rule-card-baseline.md
  design/teardown-design-rules-v3.md 参考副本
  design/teardown-tokens.css         参考副本
src/
  rotation/  etf_probe · analyze · analyze2 · signals · gen_panel · signals_r_breakdown
  home/      gen_directions · gen_home · gen_home2
  research/  build_hfq · baseline · enh_engine · is_mining · oos_run · characterize ·
             characterize_extra · universe_breadth · dividend_spread_check · dividend_sizing_controls
prototypes/  rotation-panel/ · home/ · README.md（导航）
requirements.txt
```

**文档**：9 份文档只在一级标题后插入 Metadata 块，正文与 claude.ai Project 版本逐字一致（脚本比对通过）。两份设计参考来自 `lwx0218/serenity_quant_research@1c3311c`（`docs/product/design-rules.md`、`web/src/styles/tokens.css`），原文未改，只在标题下 / 文件头加了来源说明，并注明 CPO 部件与爆炸图材质条目不适用于本项目。

**代码**：14 个既有脚本 + 5 个此前只在会话里跑过、其数字被文档引用的一次性分析（`signals_r_breakdown`、`characterize_extra`、`universe_breadth`、`dividend_spread_check`、`dividend_sizing_controls`），留存为文件以便复现。相对原脚本的改动只有这些：

- 路径：沙盒绝对路径改为仓库相对（`ROOT_S` 由 `__file__` 推出）；数据仍读写 `data/`，HTML / Markdown 产物改写到 `outputs/`，**不再写进 `docs/`**（原 `characterize.py`、`baseline.py` 会覆盖同名文档）；`etf_probe.py` 默认输出从 `out/` 改为 `outputs/probe/`（`out/` 不在 .gitignore 里）。
- 可复现性：`gen_directions.py` 原把方向 A 写成 `Main.dc.html` / `MainDark.dc.html`，再靠一次手工复制改名为 `DirectionA*`；现直接写目标文件名，消除手工步骤和孤儿文件。
- 文案（Owner 要求）：面包屑 / 眉题「Teardown › ETF 轮动」改为「ETF 前向机会台账」；轮动面板上 5 处用户可见的「Kell」改为「形态状态」，正文里的状态代码（BNB / XB / XBD / EXH）改为白话名（平台突破 / 回踩 / 遇阻 / 过热）。内部数据字段名 `kell` 未改（见下一步）。
- `dividend_spread_check.py` 删去了原一次性脚本里一段因分组键错误输出为空、未被任何文档引用的逐年表。其余留存脚本逻辑未改。

**原型快照**：`prototypes/` 下 15 个文件由上述代码 + 数据快照在干净 checkout 中重新生成，不是从旧目录拷贝。claude.ai 上已发布的 2.6 MB 画布包（编辑器运行时 + 内容）未入库。

**数据（不入 Git）**：随本提交附带 `etf-ledger-data-snapshot-2026-09-25.tar.gz`，在仓库根解压得到 `data/`，共 126 个文件 + `MANIFEST.txt`（逐文件来源分组与 sha256）。所有行情是 2026-09-14 至 09-17 在沙盒里用 WebFetch 取得的；仓库里没有可以重新拉取它们的代码。

## Validation

在「本提交 + 数据快照」的干净 checkout 中（Python 3.11.15、pandas 3.0.2、numpy 2.4.4）：

- 16 个入口脚本按依赖顺序全部运行，exit 0；`py_compile` 全部通过；仓库内无沙盒绝对路径残留。
- `data/` 下被脚本重写的 12 个文件（panel_daily / weekly_replay / panel.json / signals_2026 / gaps_2026 / kline_hfq_510880 / dividends_510880 / baseline_spells / is_mining_results / oos_results / z2_events_all / hl_z_series）与快照**逐字节一致**；其余数据文件未被改动。
- `is_mining.py`、`oos_run.py` 的标准输出与 09-17 存档（`is_mining_out.md`、`oos_out.md`）逐字一致。
- 5 个留存分析复现文档引用的全部数字：完美后视 +257% / −4%、近 1 月动量前 1 +13.0% / −52%、等权 +10.4% / −35%、A 股权益容器 19% 月份无一上涨；32 笔进攻信号盈亏比 2.17、去掉最好 1/2/3 笔后 +1.0% / −0.7% / −1.6%、t = 0.94；下轨事件 68 次落在 26 个月、Kelly 2.76；利差 Spearman 0.057；仓位对照表全部数值。
- 首页 13 个文件与轮动面板：把本次文案改名反向替换回去之后，与 09-15 原件**逐字节一致**，即除改名外渲染无任何差异。
- `outputs/research/characterization.md`、`baseline_card.md` 与 `docs/` 版本的差异仅为 docs 版本里人工改过的标题、人工写的「读法与结论」段（已知，docs 版本为准）。
- `git diff --check` 报告的行尾空白只有两类来源，均有意保留：`docs/etf-card-schema-v1.md` §1 生命周期 ASCII 图里的一行（文档原文，逐字保留）；`prototypes/home/*.dc.html` 里生成器模板产生的空白行（改掉会破坏「与生成器输出逐字节一致」）。
- 无头 Chromium 渲染面板与首页：无脚本错误；仅 `./support.js` 与 Google Fonts 请求失败（前者见下，后者是沙盒网络限制）；面板上已无用户可见的「Kell」。

## 已看过什么 / 未做什么

- 没有拉取任何新数据、没有调用市场接口、没有新的统计或回测；本次出现的所有数字都是重跑已有脚本得到的既有结果。
- 未开始 intake 任务 0–7；§10 五项仍未决；没有创建实施 Plan。
- 未修改治理层文件：`AGENTS.md`、`README.md`、`Harness_manual.md`、`.pi/`、`docs/manual/`、`.gitignore`、`docs/project-intake/` 均未动。
- README 里「本仓库没有这些资产」「没有行情拉取、回测……或 UI」两句现在部分过时。README 在 Harness 交付清单里，按 AGENTS.md 不在产品 round 修改，留给 Orchestration 决定。
- claude.ai 上已发布的两个 Artifact（「2026 ETF 轮动面板」「ETF 机会首页」）仍是 09-15 版本，带旧面包屑与 Kell 字样，未重新发布。

## 已知限制

- **仓库里没有可运行的取数代码。** 快照里的行情全部来自沙盒 WebFetch；`etf_probe.py`（akshare）从未在真实接口上跑过。数据层就是 intake 任务 1。
- `top3_entries_2026*.csv` 由 09-15 会话内一次性脚本生成，源码未留存（`etf-l1-retrospective.md` 的数据来源）。
- 内部字段名 `kell` 仍出现在 `etf_probe` / `analyze` / `analyze2` / `signals` / `gen_panel` 与 `panel_daily.csv`、`panel.json` 里；改为 `state` 需要同时重算数据产物，不在本次范围。
- `.dc.html` 引用的 `./support.js` 是 Claude Design 画布运行时，仓库里没有；浏览器直接打开时该请求 404，不影响渲染。`teardown-tokens.css` 引用的 Geist 字体文件未导入。
- `src/research/` 对应的方向均已关闭（见 intake §1），保留只为让文档里的数字可复现，不是继续研究的起点。
- 结果依赖 pandas 3.x：2.x 的 `pct_change` 默认前向填充缺失值，月度统计会有细微差异，`requirements.txt` 已锁 `pandas>=3.0,<4`。

## Decision / Next Steps

- Owner 审阅本提交后自行 push；数据快照放到服务器仓库根目录解压，不提交。
- 之后仍按 intake §7：先定 §10 五项并批准实施规划，再从任务 0（指数清单核对）开始。
