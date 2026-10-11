# 项目状态（先读这个）

## 基线
- main：794a8cca082e7d2b0bd75767c533445c610d7e6f（R1 内容；R2 只在 dev）
- dev：R2 已完成。默认观察改为执行 ETF，并修回三项缺陷。本文件与代码在同一提交时，该提交就是 R2
- 行情库：data/market.sqlite，51 序列 / 152,408 行，末日 2026-09-30；38 只执行 ETF 腾讯日线全量；CSI 全收益仅 H00300 / H00015 / H00852 / H20606 / 399998（其余 403）
- 正式台账 data/ledger.sqlite：不存在（A7 未放行）
- 启动：.venv/bin/python -m src.web --port 8765（demo）；--mode readonly；--mode market
- 测试：mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .

## 现在能看到什么
- /：三态首页；demo 有合成卡；market 观察默认执行 ETF（2026-09-30 横截面 37/37，排名非空）。读数口径为「ETF 价格 · 不复权」，并注明与指数差异按年 1% 打折
- /rotation：37 容器 × 12 周的执行 ETF 相对强弱都有数值。切换研究序列仍是 10 个有效；research_ready 仍为 false
- 卡片详情在价格图之前直接写出「当时为何触发」和「现在按什么条件退出」（创建失效位、当前止损、论点失效、待成交信号分开）

## 当前 round
- R2 已完成。下一轮 R3：轮动页按原型重做

## 待办（按顺序）
1. R3 轮动页按原型重做（prototypes/rotation-panel/rotation-panel-2026.html）
2. R4 首页按原型重做（prototypes/home/Main.dc.html），market 退为 /market
3. R5 Pi 部署 readonly 为默认入口；腾讯 ETF 增量 update + cron
4. backlog：证据→草稿→确认→冻结；正式盲评分/作废/出场入口；R6 四触发器与反事实；NAV/份额/成交额；V1 放行；A7

## 原型与设计
- docs/design/teardown-design-rules-v3.md、docs/design/teardown-tokens.css
- prototypes/home/*.dc.html、prototypes/rotation-panel/
