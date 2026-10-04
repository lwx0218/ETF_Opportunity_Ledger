# 数据层 `src/data/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active（S1 实网结果见 2026-10-04 日志；离线恢复真实原文件验证待 pi）
- Owner: Faye
- Last updated: 2026-10-04（H00300 离线恢复与只读研究输入预检）
- Source of truth: `operations/planning/2026-09-29-replan-three-lanes.md` §3 P1、§8、§11；`data/universe.csv` v1；intake §4.2、§5

## 命令

```bash
python -m src.data probe    --end 2026-09-30 [--only T01,T02] [--record outputs/data/recorded/]   # coverage → 库
python -m src.data backfill --end 2026-09-30 [--exec-start 2005-01-01]   # 全量 → bars；--exec-start 只缩短执行 ETF
python -m src.data update   [--end D]               # 增量，往回多拉 10 天覆盖修正
python -m src.data calendar outputs/calendar/sse-trading-days.csv [--replace]   # astra 生成的交易日清单 → calendar 表
python -m src.data package  --end 2026-09-30 [--force]   # → outputs/research-package-2026-09-30.sqlite（+ .MANIFEST.json）
python -m src.data verify   outputs/research-package-2026-09-30.sqlite
python -m src.data compare  data/kline_510300.csv 510300 [--adj raw] --out outputs/data/diff-510300.csv
python -m src.data offline-restore --source-run-id 1 --recorded-dir outputs/data/recorded [--apply] [--db 验证副本.sqlite]
python -m src.data preflight --end 2026-09-30 [--start YYYY-MM-DD] [--db 验证副本.sqlite]  # 只读；research_ready=false 退出 1
```

所有命令默认读写 `data/market.sqlite`，`--db` 可换（`verify` 只看包本身）。只用标准库（`urllib`、`csv`、`json`、`sqlite3`），不依赖 pandas / akshare / serenity。HTTP、分段、「一条路不通退下一条」的做法抄自 `lwx0218/serenity_quant_research`（physical-first）`api/app/ingest/{http,quotes,symbols,runner}.py`；单库、schema 写在代码里、每次作业记一行、seed → 库、测试只许连临时库，也按 serenity（replan §11）。

`offline-restore` 默认只读 dry-run，明确 `--apply` 才原子写入；`preflight` 始终只读，复用现有 pandas 日历校验。完整恢复合同、计数与 pi 命令见 [H00300 离线恢复与研究输入校验](h00300-offline-restore.md)。恢复复用已有 CSI 取数方式的原响应，不增加网络来源。27 个年度响应单独入选；短窗只核验不拼入，NULL 与非交易日保留在原库。恢复作业使用现有 `backfill` 类型，以 `args.offline_restore=true` 区分。

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
- **交易日历**（schema v1.1-e，新增取数方式）：库里的 `calendar(date)` 表（replan §11，取代 `sse-trading-days.csv`）。astra 用 09-27 已验证的深交所日历接口（`monthList`）生成清单文件（一行一个 A 股交易日，`YYYY-MM-DD` 或 `YYYYMMDD`，可有表头；放 `outputs/` 下，不入 Git），覆盖 2005 年至次年，每年补一次（replan §8 astra S1），再用 `python -m src.data calendar <文件>` 写入；本仓库代码只读不抓。`calendar` 校验文件（一行多列——例如原样导出带开市标志的 monthList、第一行以外有非日期行、含周末、没有日期）并与库里已有的日子取并集后再校验一次（相邻两天间隔超过 14 天 = 中间缺一段），不过就拒绝、库不动；`--replace` 整表换成该文件。表本身也拒绝周末与非法日期。`package` 把整张表复制进数据包。用途：月末判定（P2）、owner 评分截止（P5）；表空时两处退回工作日规则，表里中间缺一段时 `build` 与 `daily` 都报错，不静默退回。

## 研究序列的选择（probe 与 backfill 相同）

1. **全收益版本**：按 `tr_code_candidates` 顺序，在该容器的首选路由上查最近 45 天；第一个有数据且名称含「全收益 / 财富 / Total Return / TR」的即采用（`tr_code_used`）。有数据但名称无标记的候选不采用，名称写进 `notes`，由 Cowork 判断（例如深交所「创业板R」按规则不会被自动采用）。
2. **声明的替代**：只有 universe v1 / replan §1 已写明的「研究 = 执行」替代才自动用——目前仅国债 H11077 → 511260 后复权。
3. **价格版本**：以上都没有时用价格指数，`price_only=True`，V1 报告按 intake §2.3 每年 1% 打折并注明。布伦特（现货或期货连续合约）不是指数，标 `price_only=n/a`：既无分红也不含展期收益，不适用 1% 规则，由 V1 报告单独说明。
4. **近似指数不采用**：纳指科技 NDXTMC 拉不到时只探测 `^NDXT` 可得与否并写进 `notes`，不自动顶替（AGENTS.md：核不到的主题剔除，不用近似指数替代；与 universe v1 的写法冲突，待 Cowork 定）。
5. 黄金的上海金 Au99.99 未尝试：固定源与 replan 均未给出接口。

## 库与表（replan §11）

`data/market.sqlite` 一个库，入 Git；`journal_mode = DELETE`（提交时不留 `-wal` / `-shm` / `-journal`），只在检查点 `VACUUM`。schema 写在 `src/data/db.py`，`meta.schema` 记版本（`market-v1`）：打开时版本不符直接拒绝（需迁移），不在旧库上补建半套表。

| 表 | 内容 |
|---|---|
| `bars` | `code, adj, date, open, high, low, close, volume, amount, source, fetched_at`，主键 `(code, adj, date)`。`adj = hfq` 只给后复权路由 `eastmoney_etf_hfq`（CHECK 约束），其余（指数点位、不复权执行价）都是 `raw`；一条序列 `(code, adj)` 只来自一个路由（触发器：已有别的来源即拒绝插入），增量换源即拒绝合并；后复权序列与采用的全收益序列在重叠区被改写（复权基准可能变了）时也拒绝合并，需重新全量 backfill。backfill 整条替换，update 按日覆盖（INSERT OR REPLACE）；UPDATE 一律拒绝（触发器），改来源只能整条重写。量额保留各源原始单位（东财 / 腾讯成交量为「手」；中证量额单位未核实）。EIA 只有收盘值 |
| `coverage` | 每次作业每容器一行（带 `run_id`，保留历史）；当前口径是视图 `coverage_latest`（每个 `theme_id` 最近一次作业那一行），`--only` 时其余容器沿用上一次的行。列：`container, code, route_used, first_date, last_date, rows, tr_code_used, price_only, error`（replan 规定列），其后 `theme_id, status, series_code, series_adj, series_name, max_gap_days, price_first_date, ohlc_missing_rows, volume_missing_rows, exec_code, exec_route, exec_first_date, exec_last_date, exec_rows, exec_error, checked_at, notes`（`series_adj` 取代 CSV 时代的 `series_file`：研究序列 = `bars` 里的 `(series_code, series_adj)`）。probe 只查执行 ETF 最近 45 天，不填 `exec_first_date / exec_rows`；`price_first_date` 只有 backfill 会填（看全收益版本是否比价格版本短、是否丢掉 ≤ 2015 的设计期）。`volume_missing_rows` 提醒形态状态机的放量条件：没有成交量的序列不会出现启动 / 超跌反弹 / 过热 / 破位四态 |
| `requests` | 每次请求的 URL、UTC 时刻、字节数、sha256、错误，按作业 `run_id`（取代三个 `*-requests.jsonl`；工程任务的证据标准，replan §6.1） |
| `update_results` | update 每条序列一行：`code, adj, route, ok, since, added, revised, last_date, error`（取代 `update-log.jsonl`） |
| `runs` | probe / backfill / update / calendar 每次一行：起止时刻、`end`、参数、git commit、universe seed 的 sha256、状态（`ok` 或 `error: …`） |
| `calendar` | A 股交易日，见上 |
| `universe` | 每次作业从 `data/universe.csv`（人手编辑的 seed，保留 CSV）装入，`meta.universe_sha256` 记 seed 的 sha256 |

- probe 与 backfill 写同一张 `coverage`；backfill 之后再跑 probe 会让 coverage 与 bars 脱节。`package` 逐个核对：研究序列必须在库里、有行、`source` 等于 `route_used`，否则该容器改记 error；只打包 coverage 引用的序列（研究、价格版本、执行），不一致的容器列在 `inconsistent_with_bars`。
- **研究数据包**：`package --end D` 只读打开源库（Cowork 在本地打包不改动入 Git 的库），复制出一个截到 D 的库 `outputs/research-package-D.sqlite`（文件权限只读）：`bars`（只含 coverage 引用的序列：研究、价格版本、执行）、`coverage`（按截断后的行数重算日期）、`calendar`、`universe`、`meta`，外加 `package` 表（`end`、git commit、源库路径与 sha256、源库是否与该 commit 一致 `source_db_matches_commit`、universe sha256、计数）与包内 `runs` 的一行。旁边 `research-package-D.MANIFEST.json` 记包文件的 sha256、**内容哈希 `content_sha256`**、打包时刻与同样的信息。包文件的字节含作业时刻、也随 SQLite 版本变，**prereg §13 记 `content_sha256`**（`meta`、`package`、`universe`、`calendar`、`coverage`、`bars` 逐表逐行的规范化哈希，同一源库、同一 D、同一 commit 在任何机器上相同）与源库 commit。universe 表缺 coverage 里的容器时拒绝打包（价格版本序列靠它认出）；中途出错不留半截包。库在 Git 里，**不再传包**：Cowork `git pull` 后自己 `package` + `build`。
- `verify` 四项：`PRAGMA integrity_check`、`bars` 行数对 coverage（研究与执行序列）、没有晚于 `end` 的行、`source = route_used`（执行序列对 `exec_route`）；另核对包文件 sha256 与 `content_sha256` 对 MANIFEST，并报 coverage 未引用的序列。坏库、坏清单、不是数据包的库都只记问题、不抛异常。MANIFEST 放在包旁边，连同它一起改写的篡改发现不了——可信的锚点是 prereg §13 里记下的 `content_sha256`。
- **测试只许连临时库**：环境变量 `ETF_LEDGER_TESTING` 置位时（`tests/__init__.py` 设置），连 `data/market.sqlite` 或 `data/ledger.sqlite` 一律报错（serenity 的硬防线）。
- **提交节奏**（replan §11）：backfill / 日历写入后提交；每日 `update` 由 astra 每周提交一次。库约 20–30 MB、每日增量几百 KB，一年内不需要 LFS。提交前确认没有 `data/*.sqlite-journal`（有热日志说明有未完成的写入），并跑一次 `python -c "import sqlite3; print(sqlite3.connect('data/market.sqlite').execute('PRAGMA integrity_check').fetchone()[0])"` 得到 `ok`。`.gitignore` 对 `data/` 用白名单：只放行 `market.sqlite`、`ledger.sqlite`、`universe.csv`、`events/`；P7 之前的 CSV 布局（`raw/`、`calendar/`、`ledger/`、`jobs/`、09-25 的 kline 快照）、回放库、临时文件一律不入 Git。`update` 与 `calendar` 要求库已存在（不在 S1 之前的机器上建空库）。

## 数据陷阱（intake §4.2）在本层的处理

1. 主题指数回填：本层不处理，`first_date` 是指数公司回填后的起点，不是发布日；V1 报告需自行声明。
2. 指数 ≠ ETF：研究序列与执行序列是 `bars` 里不同的序列（不同 `code`，后复权与不复权另以 `adj` 区分），不互相替代。
3. 腾讯减法 qfq：从不请求 qfq；`compare` 用来解释仓库 09-14 腾讯 qfq 快照与不复权序列的差（除息日处阶跃）。
4. 价格 / 全收益混用：`price_only` 逐容器标注。
