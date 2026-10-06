# 可运行的 ETF 前向机会台账

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: guide
- Status: active
- Owner: Faye
- Last updated: 2026-10-06
- Source of truth: operations/planning/2026-10-06-parallel-data-and-product.md；docs/etf-card-schema-v1.md；docs/jobs-daily.md

## 启动与复验

在仓库根目录使用 Python 3.12 及现有 requirements：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m src.web --port 8765
```

本机访问 `http://127.0.0.1:8765`，同一服务的 `/?mode=readonly` 查看正式台账。服务仅绑定 `127.0.0.1`，没有生产认证与反向代理配置；服务器部署由 Pi 另行执行，不应直接暴露至公网。远程使用可经已有 SSH 连接转发：`ssh -L 8765:127.0.0.1:8765 <Pi主机>`，再用本机浏览器访问同一地址。无 Node 构建或运行时依赖。

演示数据默认保存在忽略的 `outputs/app-demo/ledger.sqlite`。初次启动生成六张纯合成卡，初始时间为北京时间 2026-09-14 16:00；推进使用合成工作日日历，不冒充交易所日历。重启保留状态，“重置演示”恢复初始样例并清除该演示内的操作。每个演示目录只启动一个服务实例；测试和并行预览使用独立 `--demo-dir outputs/my-demo`。不接受来自 HTTP 的数据库路径、时钟、成交价格或冻结字段。

演示数据格式升级时，旧库会被明确拒绝，不自动覆盖。保留旧演示可启动新目录，例如 `--demo-dir outputs/app-demo-v2`。不得用 `data/` 作为演示目录。

完全只读启动（不初始化演示库）：

```bash
.venv/bin/python -m src.web --mode readonly --port 8765
```

正式行情与台账分别是 `data/market.sqlite`、`data/ledger.sqlite`。读取使用 SQLite URI `mode=ro` 与 `query_only`，不调用会初始化台账的 `Ledger(...)`；缺库显示空态，不建库、不迁移、不记录新来源。页头将读取时间与最新逐日观测日期分开。行情状态复用只读 quality 预检，收盘基准与研究可用性分开报告。

## 操作路径

1. 从“未来”打开国债或红利，查看冻结的论点、预期、失效条件和证据时点，填写 0–5 独立评分及理由；一次提交后封存，下一演示交易日开盘后过期。
2. 可将另一候选作废：原记录留在“已结 / 作废”，总分母不减少。
3. 从“当下”打开半导体，声明手动出场（须理由）或论点作废。提交只增加信号，仍处于持有状态。
4. 返回首页，推进一个演示交易日。现有 DailyJob 按下一有效开盘处理出场，卡片进入“过去”；继续推进记录出场后 20 日，再按冻结规则结案。
5. 深浅主题通过右上角切换；所有详情在同页展开，Escape 返回首页。正式只读入口没有写操作。

演示 OHLCV 与事件论点全部合成；指标使用已有 `src/indicators`，任务使用 `DailyJob`、`Ledger` 及原 `Params()`。演示事件只在内存中启用，绝不修改 `config/ledger-rules.json`。没有真实事件证据，样例明确登记“已检索无证据”，不伪造引用。月末 z 在预热不足时保持缺失。

## 双盲、冻结与评分审查

API 显式投影字段，不序列化带 `agent_strength` 的完整 `card_status`。Owner 入口始终不披露 agent 个体分数和理由，也不公开能反推其分桶的 agent 聚合；独立审查仍可使用已有台账校准方法。前端显示自己的校准桶，终态样本不足 30 时仅显示数量与“样本不足，不下结论”，不绘制效力曲线。作废计入分母；未评分、未检索和仍在途的数量分别保留。

审查只报告事实与触发状态，不改变规则。已接两条确定口径：最近 20 张已结卡的平均已实现 R ≤ −0.2，以及全部已出场中手动出场比例 > 30%。前者按结案记录时刻、卡号稳定排序，未满 20 张不判定。告警不代替人的“继续 / 停止 / 重开新版本”决定。

反事实区域展示创建时冻结的等权、沪深300、容器点位，以及库内已记录的所选基准已实现超额；它们不会被冒充为全部同期对照已完成。同期双基准重算需要明确可验证的窗口及端点，随机容器尚缺事前抽样池、种子与冻结时点；连续三季度反向的指标/样本门槛、年度审查起算日和结构变化的时点证据尚待编排方确认。页面列明这些未完成项，不补参数或事后随机抽样。

## 接口与测试

GET `/api/state`、`/api/cards/<id>`；POST `/api/cards/<id>/score`、`void`、`exit-signal` 及 `/api/demo/advance`、`reset`。写请求须 JSON、当前 `revision` 与 `X-CSRF-Token`；陈旧页面返回 409，同源与 Host 检查保护本机入口。评分、作废与信号继续由数据库的追加/冻结/时限约束裁定；错误不回退为任意写入。

```bash
.venv/bin/python -m unittest discover -s tests -t .
node --check src/web/static/app.js
curl --fail http://127.0.0.1:8765/api/state
```

测试仅使用临时库，涵盖领域流程、冻结/双盲、过期和重复、HTTP 边界、只读缺库、文件保全、演示失败回滚与审查触发边界。浏览器按上述操作路径复验，深浅色均检查首页与详情；运行前后可用 `sha256sum data/market.sqlite` 核对正式行情保全。

本地字体来自官方 `geist@1.7.2` npm 包（Vercel），采用 SIL OFL 1.1；许可证随 `src/web/static/fonts/LICENSE.txt` 分发。无需页面访问外部字体服务。
