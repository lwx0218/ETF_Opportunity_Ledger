# ETF 前向机会台账

A 股主题 ETF 的前向机会台账。立卡时锁死论点、证据、量化预期和失效位，之后按预先定好的规则每天跟踪、出场、评分。

## 状态

已冻结（2026-10-21）。原因：研究线拆到新项目，本项目不再开发。详见 [docs/status.md](docs/status.md)。

冻结时：服务器运行 main `6628bf520099ca716ceaaf1ad9a9ed4b45b06816`，每日 cron 已停用，网页服务仍在运行，台账 0 张卡。

## 核心概念

- **37 个主题容器**。[data/universe.csv](data/universe.csv) 有 39 行。`status` 为 `retained` 或 `flagged` 的 37 行进入面板；保险为 `excluded`，现金为 `execution_only`。
- **卡片和锁死字段**。创建时写入的论点、证据、量化预期和失效位之后不能改，只能作废重建。见 [docs/etf-card-schema-v1.md](docs/etf-card-schema-v1.md)。
- **每日作业**。交易日更新行情、写在场卡的每日行、进出场和评分。见 [docs/jobs-daily.md](docs/jobs-daily.md)。
- **校准和审查**。已结卡片按证据强度分桶，看达标率和平均 R；审查结论只有继续、停止、重开新版本。见 [docs/etf-card-schema-v1.md](docs/etf-card-schema-v1.md) 第 6 节。
- **三个触发器**。[config/ledger-rules.json](config/ledger-rules.json) 里事件驱动已开，恐慌下轨关。形态突破未接。

## 目录

- `src/data`：按宇宙清单拉取研究序列和执行 ETF 日线。
- `src/indicators`：形态、ATR20、`rs_1m`、`z_month`。
- `src/ledger`：卡片库。冻结和只追加在存储层强制。
- `src/jobs`：每日增量、指标和台账流程。
- `src/web`：本机网页。
- `src/observation`：只读行情观察，不跑研究。
- `src/scoring`：只读评分和审查事实。
- `src/research/prereg_v1`：横截面轮动的预注册验证框架。
- `src/home`：首页方向稿。
- `src/rotation`：早期轮动面板脚本。
- `config/`：规则开关 [config/ledger-rules.json](config/ledger-rules.json)。
- `data/`：[data/universe.csv](data/universe.csv) 与行情库 [data/market.sqlite](data/market.sqlite)。
- `deploy/`：服务器上的网页服务和每日作业。[deploy/README.md](deploy/README.md)。
- `docs/`：权威说明。
- `tests/`：单元测试。
- `operations/work_logs/`：工作记录，含 Pi 部署日志。
- `prototypes/`：首页和轮动的静态原型。
- `ref/`：外部参考，不参与运行。

## 怎么运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .
```

网页。默认是 demo。正式台账只读不创建库文件。

```bash
.venv/bin/python -m src.web --port 8765
.venv/bin/python -m src.web --mode readonly --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。

手动跑每日作业。正式库不存在时退出，不创建文件。补某一天加上 `--date`。

```bash
bash deploy/daily.sh
bash deploy/daily.sh --date 2026-09-30
```

步骤见 [deploy/README.md](deploy/README.md)。

## 数据

[data/market.sqlite](data/market.sqlite) 的 `bars` 表有 87 条序列、309,275 行，日期从 2000-01-03 到 2026-09-30。

[data/universe.csv](data/universe.csv) 是主题容器清单：研究指数、执行基金和状态。

## 研究资产

给新项目用：

- [docs/etf-rotation-prereg-v1.md](docs/etf-rotation-prereg-v1.md)
- [src/research/prereg_v1](src/research/prereg_v1)
- [docs/etf-dividend-enhancement-prereg.md](docs/etf-dividend-enhancement-prereg.md)

`keep/` 标签里的数据包：

- `keep/incoming/grok-sources-20261016`
- `keep/incoming/grok-sources-20261019`
- `keep/incoming/grok-nav-shares-20261019`
- `keep/incoming/grok-nav-shares-followup-20261019`
- `keep/incoming/grok-t12-identity-20261019`

## 分支和标签

- `main`：冻结后的代码和文档。
- `events`：事件草稿。目前只有 README 和空的 `events/`。
- `archive/grok-raw`：Grok 原始数据包（固定源、净值份额、T12 身份）。
- `keep/` 标签是已删除分支的存档。

## 文档索引

- [docs/status.md](docs/status.md)：当前状态。先读这个。
- [docs/etf-card-schema-v1.md](docs/etf-card-schema-v1.md)：卡片字段、评分菜单、校准和审查。
- [docs/jobs-daily.md](docs/jobs-daily.md)：每日任务的顺序和记账口径。
- [docs/events-drafts.md](docs/events-drafts.md)：事件草稿的字段和样例。
- [docs/ledger-storage.md](docs/ledger-storage.md)：台账库怎么存。
- [docs/data-layer.md](docs/data-layer.md)：行情怎么取、怎么入库。
- [docs/indicators-layer.md](docs/indicators-layer.md)：指标怎么算。
- [docs/runnable-ledger.md](docs/runnable-ledger.md)：网页的几种启动方式。
- [docs/etf-fixed-sources-v1.md](docs/etf-fixed-sources-v1.md)：固定信息源清单。
- [docs/etf-rotation-prereg-v1.md](docs/etf-rotation-prereg-v1.md)：横截面轮动预注册。结果尚未填写。
- [docs/etf-dividend-enhancement-prereg.md](docs/etf-dividend-enhancement-prereg.md)：红利 ETF 指数增强预注册。方向已关闭。
- [docs/etf-rotation-framework-v0.md](docs/etf-rotation-framework-v0.md)：轮动框架 v0。
- [docs/etf-characterization-z.md](docs/etf-characterization-z.md)：z 值与前向收益的刻画。
- [docs/etf-dividend-bet-plan-v0.md](docs/etf-dividend-bet-plan-v0.md)：红利 ETF 下注方案 v0。
- [docs/etf-rule-card-baseline.md](docs/etf-rule-card-baseline.md)：单标的增强的基线规则卡。
- [docs/etf-l1-retrospective.md](docs/etf-l1-retrospective.md)：物理催化层的回看。
- [docs/etf-thesis-log.md](docs/etf-thesis-log.md)：前向论点记录。
- [docs/h00300-offline-restore.md](docs/h00300-offline-restore.md)：沪深300全收益的离线恢复。
- [docs/h00300-year-end-supplement.md](docs/h00300-year-end-supplement.md)：沪深300全收益年末缺日的补录。
- [docs/tencent-price-index-offline.md](docs/tencent-price-index-offline.md)：腾讯价格指数的离线导入。
- [docs/design/teardown-design-rules-v3.md](docs/design/teardown-design-rules-v3.md)：界面设计规则。
- [docs/manual/document-governance.md](docs/manual/document-governance.md)：文档放在哪里。
- [docs/project-intake/etf-opportunity-ledger.md](docs/project-intake/etf-opportunity-ledger.md)：项目初始化时的研究纪律和范围。
