# 数据层 `src/data/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active（接口均未在服务器实网验证，以首次 probe 为准）
- Owner: Faye
- Last updated: 2026-09-29
- Source of truth: `operations/planning/2026-09-29-replan-three-lanes.md` §3 P1、§8；`data/universe.csv` v1；intake §4.2、§5

## 命令

```bash
python -m src.data probe    --end 2026-09-30 [--only T01,T02] [--record outputs/data/recorded/]
python -m src.data backfill --end 2026-09-30 [--exec-start 2005-01-01]   # 全量 → data/raw/（不入 Git）；--exec-start 只缩短执行 ETF
python -m src.data update   [--end D]               # 增量，往回多拉 10 天覆盖修正
python -m src.data package  --end 2026-09-30        # → outputs/research-package-2026-09-30/
python -m src.data verify   outputs/research-package-2026-09-30/
python -m src.data compare  data/kline_510300.csv data/raw/510300.csv --out outputs/data/diff-510300.csv
```

只用标准库（`urllib`、`csv`、`json`），不依赖 pandas / akshare / serenity。HTTP、分段、「一条路不通退下一条」的做法抄自 `lwx0218/serenity_quant_research`（physical-first）`api/app/ingest/{http,quotes,symbols,runner}.py`。

## 取数方式（AGENTS.md：新增取数方式必须补记）

| 路由 | 接口 | 分段 | 用于 |
|---|---|---|---|
| `csi` | `www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=&startDate=&endDate=` | 按自然年 | 中证 / 上证 / 深证指数及其全收益版本（研究池主源） |
| `eastmoney_index` | `push2his.eastmoney.com/api/qt/stock/kline/get`，secid `1.000xxx` / `0.399xxx`，`klt=101 fqt=0` | 120 天 | 创业板等不在中证 API 的指数 |
| `tencent_index` | `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=<sym>,day,<b>,<e>,400,` | 500 个日历日（< 400 行） | `eastmoney_index` 的退路；**只用不复权** |
| `eastmoney_etf_hfq` | 同东财 K 线，`fqt=2` 后复权 | 120 天 | 研究 = 执行的容器（黄金 518880；国债拉不到财富版时的 511260） |
| `eastmoney_etf` → `tencent_etf` | 东财 `fqt=0` → 腾讯不复权 | 同上 | 执行 ETF 日线（真实成交价与成交额） |
| `yahoo` → `stooq` | `query1.finance.yahoo.com/v8/finance/chart/<sym>`；`stooq.com/q/d/l/?s=` | 一次 | 海外指数 |
| `eia` → `yahoo` | `api.eia.gov/v2/seriesid/PET.RBRTE.D`（需 `EIA_API_KEY`）→ Yahoo `BZ=F` | 5000 行一页 | 布伦特（现货 → 期货；两者不拼接） |

- 失败只记一行，至多重试一次；出网策略拒绝（代理 403）不重试。任一分段请求失败即整条序列失败；拿到数据之后又出现空段（不是最后一段）也整条失败——序列中断或停更不留缺口。上市 / 基日之前的空段视为「还没有数据」；东财 rc≠0 一律是错误；中证在拿到数据之前返回的业务错误码照收，但在 notes 写明「first_date 可能被截短」，全部分段都是业务错误则报出该错误。
- 只收已收盘的 K 线：A 股路由按北京时间 15:30、海外路由按纽约时间 17:00 判断当天是否收盘，更新的一行丢弃（`notes` 记「丢弃未收盘 K 线」）。`package` 要求 `end` 在 A 股与海外都已收盘，否则拒绝。
- 请求记录与错误信息里的 `api_key` / `token` 一律脱敏为 `***`（coverage 与请求记录会进研究数据包）。
- 符号映射：中证 `93xxxx` / `Hxxxxx` 指数不猜东财或腾讯代码；海外 `NDX→^NDX`、`SPX→^GSPC`、`N225→^N225`、`HSTECH→HSTECH.HK`、`NDXTMC→^NDXTMC`、`BRENT→BZ=F`，stooq `^ndx / ^spx / ^nkx`。均未实网验证。
- 除 replan 列出的域名外，EIA 走 `api.eia.gov`，白名单需另加。
- **交易日历**（schema v1.1-e，新增取数方式）：`data/calendar/sse-trading-days.csv`，一行一个 A 股交易日（`YYYY-MM-DD` 或 `YYYYMMDD`，可有表头）。由 astra 用 09-27 已验证的深交所日历接口（`monthList`）生成，覆盖 2005 年至次年，每年补一次（replan §8 astra S1）；本仓库代码只读不抓。`package` 发现该文件就复制到数据包 `calendar/` 并进 `MANIFEST.sha256`，`MANIFEST.json` 的 `calendar_file` 标明有无。用途：月末判定（P2）、owner 评分截止（P5）；没有文件时两处退回工作日规则。

## 研究序列的选择（probe 与 backfill 相同）

1. **全收益版本**：按 `tr_code_candidates` 顺序，在该容器的首选路由上查最近 45 天；第一个有数据且名称含「全收益 / 财富 / Total Return / TR」的即采用（`tr_code_used`）。有数据但名称无标记的候选不采用，名称写进 `notes`，由 Cowork 判断（例如深交所「创业板R」按规则不会被自动采用）。
2. **声明的替代**：只有 universe v1 / replan §1 已写明的「研究 = 执行」替代才自动用——目前仅国债 H11077 → 511260 后复权。
3. **价格版本**：以上都没有时用价格指数，`price_only=True`，V1 报告按 intake §2.3 每年 1% 打折并注明。布伦特（现货或期货连续合约）不是指数，标 `price_only=n/a`：既无分红也不含展期收益，不适用 1% 规则，由 V1 报告单独说明。
4. **近似指数不采用**：纳指科技 NDXTMC 拉不到时只探测 `^NDXT` 可得与否并写进 `notes`，不自动顶替（AGENTS.md：核不到的主题剔除，不用近似指数替代；与 universe v1 的写法冲突，待 Cowork 定）。
5. 黄金的上海金 Au99.99 未尝试：固定源与 replan 均未给出接口。

## 文件与字段

- `data/raw/<code>.csv`，后复权序列为 `<code>.hfq.csv`；列 `date, open, high, low, close, volume, amount, source`。一个文件只来自一个路由，增量换源即拒绝合并；后复权序列与采用的全收益序列在重叠区被改写（复权基准可能变了）时也拒绝合并，需重新全量 backfill。量额保留各源原始单位（东财 / 腾讯成交量为「手」；中证量额单位未核实）。EIA 只有收盘值。
- `outputs/data/coverage.csv`：`container, code, route_used, first_date, last_date, rows, tr_code_used, price_only, error`（replan 规定列），其后 `theme_id, status, series_code, series_file, series_name, max_gap_days, price_first_date, ohlc_missing_rows, volume_missing_rows, exec_code, exec_route, exec_first_date, exec_last_date, exec_rows, exec_error, checked_at, notes`。probe 只查执行 ETF 最近 45 天，不填 `exec_first_date / exec_rows`；`price_first_date` 只有 backfill 会填（看全收益版本是否比价格版本短、是否丢掉 ≤ 2015 的设计期）。`volume_missing_rows` 提醒形态状态机的放量条件：没有成交量的序列不会出现启动 / 超跌反弹 / 过热 / 破位四态。
- `outputs/data/probe-requests.jsonl` / `backfill-requests.jsonl` / `update-requests.jsonl`：每次请求的 URL、UTC 时刻、字节数、sha256、错误（工程任务的证据标准，replan §6.1）。
- probe 与 backfill 写同一个 `coverage.csv`；backfill 之后再跑 probe 会让 coverage 与 raw 脱节。`package` 逐个核对：`series_file` 必须存在、有行、`source` 等于 `route_used`，否则该容器改记 error；只打包 coverage 引用的文件，不一致的容器列在 `MANIFEST.json` 的 `inconsistent_with_raw`。
- 研究数据包：`raw/`（只含 coverage 引用的文件，截到 end）、`coverage.csv`（按截断后的文件重算日期）、`universe.csv`、`calendar/sse-trading-days.csv`（有才带）、`MANIFEST.sha256`（`sha256sum -c` 可用）、`MANIFEST.json`。

## 数据陷阱（intake §4.2）在本层的处理

1. 主题指数回填：本层不处理，`first_date` 是指数公司回填后的起点，不是发布日；V1 报告需自行声明。
2. 指数 ≠ ETF：研究序列与执行序列分文件保存，不互相替代。
3. 腾讯减法 qfq：从不请求 qfq；`compare` 用来解释仓库 09-14 腾讯 qfq 快照与不复权序列的差（除息日处阶跃）。
4. 价格 / 全收益混用：`price_only` 逐容器标注。
