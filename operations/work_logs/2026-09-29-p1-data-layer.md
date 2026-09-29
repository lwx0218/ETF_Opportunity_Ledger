# P1 · 数据层 `src/data/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §3 P1——数据层代码 + probe（数据源可用性的最小验证）
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示「按 §3 从 P1 开始，P1 先交 probe」）
- Source of truth: `operations/planning/2026-09-29-replan-three-lanes.md` §3 P1、§6；`data/universe.csv` v1；AGENTS.md

## 结果

| 项 | 结果 |
|---|---|
| probe 实跑（CC 云端，`--end 2026-09-29`） | 39 行；面板容器 37 个：有路由 **0**，明确 error **37**；T29 已剔除不拉取；T34 只查执行序列（也失败） |
| 失败原因 | 出网策略拒绝。curl 预检 replan 列的 7 个域名（www / oss-ch.csindex、web.ifzq.gtimg、push2his.eastmoney、query1.finance.yahoo、stooq、www.eia.gov）CONNECT 全部 403；probe 实际请求了其中 5 个 host（代码不用 oss-ch；EIA 因未设 key 没发请求，且走的是 `api.eia.gov`） |
| 请求记录 | 167 次请求全部失败，逐条写入 `outputs/data/probe-requests.jsonl`（sha256 `f083fffe…`）；coverage.csv sha256 `3097eb12…`（均不入 Git） |
| 单元测试 | `python -m unittest discover -s tests -t .`：78 个全过（原 31 + 数据层 47） |
| 完成判据「37 个面板容器每个有 route_used 或明确 error」 | 形式上满足；**实质判据（有路由）须在服务器上重跑 probe**（astra S1） |
| 包末复核 | 首轮 `approve_with_follow_up`，F1–F10 修掉；复验 `approve_with_follow_up`，新指出的 4 条小问题也已修掉（见下） |

## 复核发现与处理

| # | 发现 | 处理 |
|---|---|---|
| F1 | EIA key 会随 URL 进 coverage / 请求记录 / 数据包 | 请求记录与错误信息统一脱敏 `api_key=***`；加测试 |
| F2 | probe 与 backfill 共用 coverage，package 不核对文件，可能把价格指数标成全收益 | package 逐容器核对 `series_file` 存在、有行、`source = route_used`，不符改记 error 并列入 MANIFEST.json；只打包 coverage 引用的文件；update 遇到 coverage 指向的文件不存在即报错 |
| F3 | 盘中 / 美股未收盘的实时 K 线可能被冻结进数据包 | 按路由丢弃未收盘 K 线（A 股 15:30 北京、海外 17:00 纽约）；package 拒绝未全部收盘的 `end` |
| F4 | 数据中间的空段只进 notes，留下缺口 | 东财检查 `rc`；拿到数据后再出现空段（非最后一段）整条失败；执行序列也记缺口；coverage 加 `max_gap_days` |
| F5 | Yahoo 用当前 gmtoffset 换算全部历史 | 按 `exchangeTimezoneName` 逐根换算；加夏令时测试 |
| F6 | update 不留请求记录；IncompleteRead 未捕获 | 写 `update-requests.jsonl`；捕获 `http.client.HTTPException` |
| F7 | 后复权 / 全收益序列重叠区被改写会形成两套基准拼接 | 这类序列 revised > 0 即拒绝合并，要求重新全量 backfill |
| F8 | compare 容差等于最小价位，四舍五入被报成阶跃 | 默认容差 1.5 个最小价位；加测试 |
| F9 | 布伦特标 `price_only=False` 会被读成「不用打折」 | 改标 `n/a`，文档说明 |
| F10 | 本日志对出网失败的表述不准 | 已改（见上表） |

另按复核建议：coverage 加 `price_first_date`、`ohlc_missing_rows`、`volume_missing_rows`，供 P2 与 Cowork 判断。

复验新指出、已修：
1. 业务错误码会静默截短起点：东财 rc≠0 一律报错（上市前是 rc=0 + 空数据）；中证在拿到数据前返回的业务错误照收但写进 notes「起点前 N 段返回业务错误，first_date 可能被截短」。
2. 全部分段都是业务错误时只记「0 行」：改为报出最后一个错误码与信息。
3. 缺 tzdata 时 probe 中断：北京用固定 +8；纽约缺时区库时按 UTC−5（收盘判定更保守）。
4. 「用 `--start` 缩短」会丢设计期：删去该建议，新增只缩短执行 ETF 起点的 `backfill --exec-start`。

## 交付

- `src/data/`：`http.py`、`sources.py`、`universe.py`、`store.py`、`runner.py`、`__main__.py`（probe / backfill / update / package / verify / compare）。
- `tests/data/`：fixtures 解析、分段与空段、回退、全收益识别、声明替代、近似指数不采用、未收盘过滤、增量修正与防拼接、打包一致性与截断、MANIFEST 复验、脱敏、qfq 差值阶跃。
- `docs/data-layer.md`：取数方式补记、研究序列选择规则、文件与字段。

## 与 replan 的差异与待决

1. **fixtures 是构造的，不是录制的**：出网被拒，无法录制。格式依据见 `tests/data/fixtures/README.md`；astra 首次跑 `probe --record outputs/data/recorded/` 后替换。
2. **纳指科技**：universe v1 写「拉不到 NDXTMC 就用 ^NDXT 代研究序列」，与 AGENTS.md「不用近似指数替代」冲突；代码按 AGENTS.md 只探测不采用，待 Cowork 定。
3. **创业板R 类名称**：全收益识别按 replan 字面规则（名称含全收益 / 财富 / Total Return，另加英文 TR）；深交所「xxxR」不会自动采用，名称写进 notes。
4. **EIA**：用 API v2（需免费 key，域名 `api.eia.gov`，不在 replan 白名单里）；无 key 时退到 Yahoo `BZ=F`，两者不拼接。
5. **09-14 腾讯快照比对**：`data/kline_*.csv` 不在 Git，本环境无数据；`compare` 命令已备好，随 S1 执行。

## 下一步（astra S1 注意事项）

- 顺序：`probe --record` → 全量 `backfill --end 2026-09-30`（不带 `--only`）→ `package --end 2026-09-30` → `verify`。backfill 之后不要再跑 probe（package 会把不一致的容器标 error，但数据就缺了）。
- `package --end 2026-09-30` 要等北京时间 2026-10-01 05:00（美股 09-30 收盘）之后。
- 首次实网重点看：中证对基日之前年份的返回（notes 里若出现「first_date 可能被截短」要逐条看）；T07（931743）中证元数据发布日早于基日，若早年只有零星几行、之后整年为空，会按空段规则整条失败，看它的 error。
- 东财执行序列从 2000 年按 120 天分段约 82 次请求 / 只，41 条序列约 80 分钟；若被限流用 `backfill --exec-start 2005-01-01` 之类只缩短执行序列，**不要调 `--start`**（会丢研究序列的设计期）。
- 服务器需有 tzdata（`python -c "import zoneinfo; zoneinfo.ZoneInfo('America/New_York')"`）；缺了也能跑，但收盘判定按冬令时，夏令时期间会多等一小时。
