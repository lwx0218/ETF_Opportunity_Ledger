# 项目状态（先读这个）

## 基线
- main：794a8cca082e7d2b0bd75767c533445c610d7e6f（R1 内容；R2 只在 dev）
- dev：9cb2b54ad36c677fef6f98301d2f197ba7ac5b35（R4 内容：首页按六问重做，行情登记改到 /market）
- 行情库：data/market.sqlite，87 序列 / 309,275 行，末日 2026-09-30；38 只执行 ETF 腾讯日线全量；CSI 全收益 18 个容器，仅价格指数 15 个，无研究序列 3 个（T16 / T36 / T38）；回填在 Cursor 沙箱完成（operations/work_logs/2026-10-11-csi-research-backfill.md），Pi 服务器 IP 对 csindex 仍 403
- 正式台账 data/ledger.sqlite：不存在（A7 未放行）
- 启动：.venv/bin/python -m src.web --port 8765（demo）；--mode readonly；--mode market
- 测试：mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .

## 现在能看到什么
- /：六问首页。demo 有合成卡时 h1 为「1 笔正在验证，2 笔等待进场。」，三栏是黄金（过去）、半导体（当下）、红利与国债（候选）。无正式卡时（market，以及正式库不存在的 readonly）2026-09-30 执行 ETF：h1「37 个容器里 3 个处于可进态，没有在跑的判断。」下一个栏是地产 512200 / 回踩 / 名次 3 / +12.1% / +0.9 ATR；其余可进态为银行 512800、创新药 159992。今天不碰是 0 个不利，并写明 25 个形态可用、12 个不可用。规则段写前向样本不足。readonly 的页脚和模式标签是「正式台账 · 只读」；market 是「真实观察 · 只读」，规则状态是「规则未启用」。首页不再放 37 容器平铺、L1–L4 和行情登记长表
- /market：与 market 模式首页相同，页脚上方保留「辅助检查 · 行情登记」。顶栏仍是机会 / 轮动；面包屑为 ETF 前向机会台账 › 机会 › 行情检查。`?mode=market` 的旧链接仍打开同一首页，但不渲染登记表
- /rotation：37 容器 × 12 周热力格。颜色是近 1 月相对沪深300全收益的超额，格内是当周名次，小字是形态。格子颜色是 CSS 类（heat-up / heat-down），不写内联 style。2026-09-30 执行序列：8 个分组，h1「纳指科技最强，原油和地产跟着。」，超额 +18.9%。点一格后，焦点段在格子下方。研究序列横截面不完整（10/37），不排名次。L1–L4 仍只写在本文件，不占轮动页
- 卡片详情在价格图之前直接写出「当时为何触发」和「现在按什么条件退出」（创建失效位、当前止损、论点失效、待成交信号分开）
- 研究序列切换：37 个容器中 34 个有合格相对强弱（缺 T16/T36/T38）；research_ready 仍为 false

## 当前 round
- R4 已完成。下一轮 R5：Pi 部署 readonly 为默认入口；腾讯 ETF 增量 update + cron。CSI 限流见待办

## 待办（按顺序）
1. R5 Pi 部署 readonly 为默认入口；腾讯 ETF 增量 update + cron
2. 服务器 IP 对 CSI 约 50 个请求即 403。R5 的每日 update 需要 1.5 秒间隔，403 后等 90 秒重试一次，或把 CSI 部分挪到服务器以外跑
3. backlog：证据→草稿→确认→冻结；正式盲评分/作废/出场入口；R6 四触发器与反事实；NAV/份额/成交额；V1 放行；A7

## 原型与设计
- docs/design/teardown-design-rules-v3.md、docs/design/teardown-tokens.css
- prototypes/home/*.dc.html、prototypes/rotation-panel/
