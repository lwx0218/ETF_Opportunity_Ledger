# 项目状态（先读这个）

## 基线
- main：794a8cca082e7d2b0bd75767c533445c610d7e6f（R1 内容；R2 只在 dev）
- dev：e7b6118fca5209aa2d5e221670d8bcdf5e53f9e8（R3 内容：热力格颜色改为 CSS 类）
- 行情库：data/market.sqlite，51 序列 / 152,408 行，末日 2026-09-30；38 只执行 ETF 腾讯日线全量；CSI 全收益仅 H00300 / H00015 / H00852 / H20606 / 399998（其余 403）
- 正式台账 data/ledger.sqlite：不存在（A7 未放行）
- 启动：.venv/bin/python -m src.web --port 8765（demo）；--mode readonly；--mode market
- 测试：mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .

## 现在能看到什么
- /：三态首页；demo 有合成卡；market 观察默认执行 ETF（2026-09-30 横截面 37/37，排名非空）。读数口径为「ETF 价格 · 不复权」，并注明与指数差异按年 1% 打折。首页本轮未改，留给 R4
- /rotation：37 容器 × 12 周热力格。颜色是近 1 月相对沪深300全收益的超额，格内是当周名次，小字是形态。格子颜色是 CSS 类（heat-up / heat-down），不写内联 style。2026-09-30 执行序列：8 个分组，h1「纳指科技最强，原油和地产跟着。」，超额 +18.9%。点一格后，焦点段在格子下方。研究序列横截面不完整（10/37），不排名次。L1–L4 仍只写在本文件，不占轮动页
- 卡片详情在价格图之前直接写出「当时为何触发」和「现在按什么条件退出」（创建失效位、当前止损、论点失效、待成交信号分开）

## 当前 round
- R3 已完成。下一轮 R4：首页按原型重做（prototypes/home/Main.dc.html），market 退为 /market

## 待办（按顺序）
1. R4 首页按原型重做（prototypes/home/Main.dc.html），market 退为 /market
2. R5 Pi 部署 readonly 为默认入口；腾讯 ETF 增量 update + cron
3. backlog：证据→草稿→确认→冻结；正式盲评分/作废/出场入口；R6 四触发器与反事实；NAV/份额/成交额；V1 放行；A7

## 原型与设计
- docs/design/teardown-design-rules-v3.md、docs/design/teardown-tokens.css
- prototypes/home/*.dc.html、prototypes/rotation-panel/
