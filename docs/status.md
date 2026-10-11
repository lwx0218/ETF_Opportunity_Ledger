# 项目状态（先读这个）

## 基线
- main：06e7db5d2a9f96bbcff610fcc61771f6d63b405d
- 行情库：data/market.sqlite，51 序列 / 152,408 行，末日 2026-09-30；38 只执行 ETF 腾讯日线全量；CSI 全收益仅 H00300 / H00015 / H00852 / H20606 / 399998（其余 403）
- 正式台账 data/ledger.sqlite：不存在（A7 未放行）
- 启动：.venv/bin/python -m src.web --port 8765（demo）；--mode readonly；--mode market
- 测试：mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .

## 现在能看到什么
- /：三态首页；demo 有合成卡；readonly/market 无卡，显示真实观察
- /rotation：37 容器 × 12 周；当前默认研究序列，27 个容器因 CSI 403 显示「条件不足」（R2 修）

## 当前 round
- R2：修 PR #26 三项退回缺陷 + 观察序列默认改执行 ETF

## 待办（按顺序）
1. R3 轮动页按原型重做（prototypes/rotation-panel/rotation-panel-2026.html）
2. R4 首页按原型重做（prototypes/home/Main.dc.html），market 退为 /market
3. R5 Pi 部署 readonly 为默认入口；腾讯 ETF 增量 update + cron
4. backlog：证据→草稿→确认→冻结；正式盲评分/作废/出场入口；R6 四触发器与反事实；NAV/份额/成交额；V1 放行；A7

## 原型与设计
- docs/design/teardown-design-rules-v3.md、docs/design/teardown-tokens.css
- prototypes/home/*.dc.html、prototypes/rotation-panel/
