# 项目状态（先读这个）

## 基线
- main：357130fb4cf45b64982247d5874428a6d5542dc6（已快进到 R4）
- dev：b9a30ea63a46a710bba9411889984cf43d546567（R5 内容：正式手动立卡、每日维护、记录文件去掉时区标注）
- 行情库：data/market.sqlite，87 序列 / 309,275 行，末日 2026-09-30；38 只执行 ETF 腾讯日线全量；CSI 全收益 18 个容器，仅价格指数 15 个，无研究序列 3 个（T16 / T36 / T38）；回填在 Cursor 沙箱完成（operations/work_logs/2026-10-11-csi-research-backfill.md），Pi 服务器 IP 对 csindex 仍 403
- 正式台账 data/ledger.sqlite：不存在（A7 未放行）
- 启动：.venv/bin/python -m src.web --port 8765（demo）；--mode readonly；--mode readonly --write（须 LEDGER_WRITE_TOKEN，至少 16 字符）；--mode market
- 测试：mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .

## 现在能看到什么
- /：六问首页。demo 有合成卡时 h1 为「1 笔正在验证，2 笔等待进场。」，三栏是黄金（过去）、半导体（当下）、红利与国债（候选）。无正式卡时（market，以及正式库不存在的 readonly）2026-09-30 执行 ETF：h1「37 个容器里 3 个处于可进态，没有在跑的判断。」下一个栏是地产 512200 / 回踩 / 名次 3 / +12.1% / +0.9 ATR；其余可进态为银行 512800、创新药 159992。今天不碰是 0 个不利，并写明 25 个形态可用、12 个不可用。规则段写前向样本不足。readonly 的页脚和模式标签是「正式台账 · 只读」；market 是「真实观察 · 只读」，规则状态是「规则未启用」。首页不再放 37 容器平铺、L1–L4 和行情登记长表
- /market：与 market 模式首页相同，页脚上方保留「辅助检查 · 行情登记」。顶栏仍是机会 / 轮动；面包屑为 ETF 前向机会台账 › 机会 › 行情检查。`?mode=market` 的旧链接仍打开同一首页，但不渲染登记表
- /rotation：37 容器 × 12 周热力格。颜色是近 1 月相对沪深300全收益的超额，格内是当周名次，小字是形态。格子颜色是 CSS 类（heat-up / heat-down），不写内联 style。2026-09-30 执行序列：8 个分组，h1「纳指科技最强，原油和地产跟着。」，超额 +18.9%。点一格后，焦点段在格子下方。研究序列横截面不完整（10/37），不排名次。L1–L4 仍只写在本文件，不占轮动页
- 卡片详情在价格图之前直接写出「当时为何触发」和「现在按什么条件退出」（创建失效位、当前止损、论点失效、待成交信号分开）
- 正式立卡：`python -m src.ledger init --db data/ledger.sqlite` 显式建库；网页和每日作业都不自动建。readonly 加 `--write` 且设置 `LEDGER_WRITE_TOKEN` 后，右上角「登录记账」（HttpOnly、SameSite=Strict，12 小时）。登录后首页「下一个」栏有「立卡」，表单在 `/new`，只接受事件驱动卡；论点、证据、量化预期、失效位提交即冻结。详情页可作废、作废并重建、手动出场信号、Owner 独立评分。手动卡不生成 agent 分。未登录这些入口不出现。不加 `--write` 的 readonly 仍完全只读
- 每日维护：`python -m src.jobs daily --maintain-only --rules config/ledger-rules.json`。不扫描、不要求启用规则，只给在场卡写进场、每日行、失效位与移动止盈、待成交出场、跟踪与到期评分。没有在场卡时只更新行情并 mark_processed。默认增量范围是 37 个执行 ETF 与 H00300；中证请求至少间隔 1.5 秒，403 等 90 秒重试一次，再失败则非零退出且不覆盖已有数据。同一交易日重跑不改变结果。Pi 步骤在 `deploy/README.md`
- 研究序列切换：37 个容器中 34 个有合格相对强弱（缺 T16/T36/T38）；research_ready 仍为 false

## 当前 round
- R5 已完成。下一轮 R6：按 deploy/ 在 Pi 上部署，并开始连续 5 个交易日无人值守计数

## 待办（按顺序）
1. R6：Pi 部署 + 连续 5 个交易日计数。代码已对中证请求间隔 1.5 秒，403 等 90 秒重试一次；若服务器 IP 仍被拒绝，作业非零退出且不覆盖已有行情
2. backlog：证据→草稿→确认→冻结；四触发器与反事实；NAV/份额/成交额；V1 放行；A7

## 原型与设计
- docs/design/teardown-design-rules-v3.md、docs/design/teardown-tokens.css
- prototypes/home/*.dc.html、prototypes/rotation-panel/
