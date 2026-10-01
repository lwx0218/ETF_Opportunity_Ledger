# P7 · 数据层改 SQLite、数据入 Git

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §11 P7——`src/data`、`src/indicators` 读写、`src/research/prereg_v1/panel.py`、`src/ledger`（`ew_daily` 表、版本）、`src/jobs`、`.gitignore`、四份文档（阻塞 astra S1）
- Timestamp (UTC): 2026-10-01
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示「先 P7，再 P6e-1，最后 P6e-2」）
- Source of truth: replan §11（Owner 决定，Claude 展开）；main `0ad4aed`

## 结果

| 项 | 结果 |
|---|---|
| 行情库 | `data/market.sqlite`，schema 写在 `src/data/db.py`（`meta.schema = market-v1`，版本不符拒绝打开、不补建半套表）；`journal_mode = DELETE`。表：`bars`（主键 `(code, adj, date)`，`adj = hfq` 只给 `eastmoney_etf_hfq`，触发器挡同一序列换来源、拒绝 UPDATE）、`coverage`（带 `run_id` 保留历史，视图 `coverage_latest` 取每容器最近一行）、`requests`、`update_results`、`runs`、`calendar`（拒绝周末与非法日期）、`universe`（每次作业从 seed 装入，记 sha256）、`meta` |
| 数据层命令 | probe / backfill / update / calendar（新增：校验 astra 的交易日清单，与已有日子取并集再校验，`--replace` 整表换）/ package / verify / compare，全部 `--db`；update 与 calendar 要求库已存在。取数函数（`sources.py`）与 `collect` 的取数逻辑未改；coverage 列 `series_file` 改为 `series_adj`（研究序列 = `bars` 里的 `(series_code, series_adj)`） |
| 研究数据包 | `package --end D` **只读**打开源库，复制截到 D 的 `outputs/research-package-D.sqlite`（只读文件：bars / coverage / calendar / universe / meta + `package` 表 + 包内 `runs` 一行）与 `research-package-D.MANIFEST.json`（文件 sha256、**内容哈希 `content_sha256`**、打包时刻、end、git commit、源库 sha256、源库是否与 commit 一致、计数）。universe 表缺容器即拒绝；中途出错不留半截包。`verify`：`PRAGMA integrity_check`、行数对 coverage、无晚于 end 的行、`source = route_used`，另核对文件与内容哈希、报 coverage 未引用的序列；坏库 / 坏清单只记问题不抛异常 |
| 面板 | `build` 读包库，输出 `outputs/panel-D.sqlite`（`panel`、`bench`、`meta` 三表；`data_hole` CHECK 0 / 1；不含生成时刻，同一个包 build 出的库逐字节相同）与 `panel-D.build-report.json`（含包与面板的内容哈希）；指标计算一行未动。V1 的 OOS 锁另记面板内容哈希。`prereg_v1/panel.py` 加 `read_table(库, panel|bench)`，`run.py` 改读库、`--bench` 默认同一个库；其余研究代码不动 |
| 台账 | `ew_daily` 表（只追加、日期递增、第一条 1、点位逐日连乘，触发器核对）取代 `data/ledger/ew_daily.csv`；`job_days` 表取代 `data/jobs/processed-days.txt`；`SCHEMA_VERSION` `v1.1-g` → `v1.1-g.1`（旧库拒绝）；`journal_mode = DELETE` |
| 每日任务 | `daily` 读写 `market.sqlite`（`--market`），`live_panel` 只读打开库、仍共用 `research_frame`；漏跑检查与等权都在台账库，运行前检查在打开台账库之前做（被拦下不建空库）；`replay` 读面板库，`--calendar` 指向带日历的库。`ew_path_for` / `unpaired`（库与库旁文件配对）随文件一起删掉 |
| Git | `.gitignore` 对 `data/` 用白名单：只放行 `market.sqlite`、`ledger.sqlite`、`universe.csv`、`events/`；`-wal` / `-shm` / `-journal`、`.env`、P7 之前的 CSV 布局（`raw/`、`calendar/`、`ledger/`、`jobs/`、09-25 kline 快照）、回放库、临时文件都不入 Git；`outputs/` 继续忽略 |
| 测试只许连临时库 | `tests/__init__.py` 置 `ETF_LEDGER_TESTING=1`（各测试文件都 `import tests`，单独当脚本跑也生效）；`db.connect`、`Ledger`、`load_trading_days`、`package`、各作业碰到默认库路径即报错（拒绝发生在建文件之前） |
| 测试 | `python -m unittest discover -s tests -t .`：220 个全过（原 207 个全部改到库口径，净增 13）。新增：`bars` 约束（主键、`adj` 取值、`hfq` ⇔ 后复权路由、换来源拒绝、非法日期）、日历表拒绝周末、旧 schema 拒绝（读写两种打开）、测试连默认库即报错（行情库、台账库、日历、probe、package）、`package` 截断 + 只读源库（源库 sha256 不变）+ 只读文件、`verify` 逐项各造一处问题只报那一项（哈希、晚于 end、行数、来源、清单外序列；缺 MANIFEST、不是库）、包带日历、backfill 整条替换、update 无 coverage 拒绝并记 error、日历装入取并集与四种拒绝、**面板库与旧 CSV 在同一构造数据上经 `panel.py` 逐行相等**（CSV 浮点往返 1e-12，读库与内存 DataFrame 逐位相等）、`daily` CLI 在临时行情库上跑（只读行情库、已处理日与等权进台账库、漏跑拒绝）、`ew_daily` 删改与乱序被拒、篡改与漏跑仍被每日任务拦下。复核后补：`integrity_check`（索引与表不一致，只有它发现得了）、内容哈希不符、坏 MANIFEST、对非数据包跑 verify、来源 ≠ route_used 进包标不一致、universe 缺容器拒绝、中途失败不留半截包、两次打包内容哈希相同、面板库两次 build 逐字节相同、价格版本随包走后借量照旧、整列 NULL 读成 float NaN、`bars` 拒绝 UPDATE、update / calendar 无库拒绝且不建库、ew 首条非 1 与表里没有的更早日期被拒、被阻断不记已处理、周六被拦下不建台账库、v1.1-g 旧台账库拒绝、OOS 锁记内容哈希 |
| 文档 | `docs/data-layer.md`（命令、库与表、研究数据包、verify、提交节奏）、`docs/indicators-layer.md`（输入输出）、`docs/ledger-storage.md`（两张新表、版本、入 Git）、`docs/jobs-daily.md`（命令、日历、等权表、漏跑检查） |

### astra S1 用法（replan §12 astra 第 4 条）

```bash
python -m src.data probe --end 2026-09-30 --record outputs/data/recorded/
python -m src.data backfill --end 2026-09-30
python -m src.data calendar outputs/calendar/sse-trading-days.csv     # 深交所 monthList 生成的清单，一行一个交易日
# 北京时间 05:00 之后
python -m src.data package --end 2026-09-30
python -m src.data verify outputs/research-package-2026-09-30.sqlite
git add data/market.sqlite && git commit …                            # 库文件提交前没有 -journal / -wal
```

## 包末复核

只读 reviewer 结论 `approve_with_follow_up`。新旧两版在同一套假网络数据上端到端对拍（backfill → package → build → live_panel，含借量、后复权、6 周断档、美股假期、缺开盘、高低价未包住收盘、D 之后的行）：面板的 `date / container / open / close / state / rs_1m / z_month / data_hole`、基准两列、build-report 各容器统计、`live_panel` 逐位相同；`high / low / atr20` 有 ≤ 1 ulp 的差（最大 4.5e-13），来自旧版 `pd.read_csv` 的浮点解析，库里的值与 round-trip 解析的旧 CSV 逐位相等。取数、指标、信号、引擎代码没有改动。32 个变异抓住 23 个，漏掉的已补测试（两个属冗余防线，见下表）。

| # | 发现 | 处理 |
|---|---|---|
| F1 | 数据包与面板库的 sha256 不可复现（含作业时刻），prereg §13 记的值别人复现不了 | 加内容哈希 `content_sha256`（逐表逐行规范化，跨机器、跨 SQLite 版本不变）进 MANIFEST、build-report 与 OOS 锁；`package` 表与面板库 `meta` 去掉生成时刻（只进 MANIFEST / 报告），面板库同包逐字节相同；verify 核对内容哈希 |
| F2 | AGENTS.md「数据库…不入 Git」与 §11 冲突；`.gitignore` 放行过宽（旧 CSV 布局、回放库、临时文件都能被 `git add data/` 带进去） | `.gitignore` 改白名单（见上）；AGENTS.md 属治理层，本包不改，见下方交 Cowork 第 1 条，**须在 astra 提交 `market.sqlite` 之前处理** |
| F3 | `bars` 的 UPDATE 能绕过来源触发器；package 中途失败留下半截包 | 加 `bars_no_update` 触发器；package 出错删掉半截文件 |
| F4 | verify 遇到坏库 / 坏 JSON / 非数据包直接抛异常 | 全部转为问题条目；integrity_check 不是 ok 即返回 |
| F5 | 测试缺口：integrity_check、ew 首条、ew 日期顺序（原用例被主键挡下）、来源 ≠ route_used 进包、被阻断不记已处理、`read_table` 的 NULL / float、v1.1-g 旧库 | 均已补（见测试一行）。`job_days` 去重触发器与主键重复、package 以读写方式打开源库测不出字节差，两条接受 |
| F6 | update / daily 在没有库时先建空库再报错 | update、calendar 要求库已存在；daily 先做运行前检查再打开台账库 |
| F7 | package 依赖源库 universe 表认出价格版本序列，表缺行时静默漏掉；测试夹具从不装 universe | universe 缺 coverage 里的容器即拒绝；夹具装入 seed，端到端测试走「价格版本进包 → 借量」 |
| F8 | schema 文档旧路径；`run.py` 提示文件名；缺工作日志 | 提示改为 `panel-D.build-report.json`；本日志；schema 文档交 Cowork |
| F9 | 单独把某个测试文件当脚本跑时测试防线不生效 | 各测试文件 `import tests` |
| F10 | 有热日志时提交，库文件可能不一致 | `docs/data-layer.md` 提交节奏一条写明：提交前无 `-journal`、`integrity_check = ok` |

## 交 Cowork 留意

- **AGENTS.md 与 Owner 决定冲突（治理层，本包未改；须在 astra 把 `market.sqlite` 提交到 main 之前处理）**：AGENTS.md「交付边界」写「密钥、认证信息、依赖缓存、**数据库**、**批量行情**和重型输出不入 Git」，与 replan §11 的 Owner 决定（`market.sqlite`、`ledger.sqlite` 入 Git）相反。按 AGENTS.md「产品 round 不修改治理层」，本包按 Owner 决定实现、不改 AGENTS.md；请 Cowork / Owner 单独改那一句（例如「数据库与行情按 replan §11 入 Git；密钥、认证信息、依赖缓存、`outputs/` 重型产物不入 Git」）。
- **`package` 只读源库，不在源库 `runs` 记打包作业**：§11 表里 `runs` 记「probe / backfill / update / package 的起止」。若打包写源库的 `runs`，Cowork 每次本地 `package` 都会改动入 Git 的 `market.sqlite`（工作区变脏，之后 `git pull` 冲突），记下的源库 sha256 也立刻过时。改为：源库只读打开；这次打包记在包内的 `runs` 与 `package` 表，MANIFEST 记源库 sha256 与「源库是否与 HEAD 一致」（`source_db_matches_commit`）。prereg §13 记包的 sha256 + 源库 commit 时，请同时看这一项为 true。请确认。
- **权威文档里的旧路径（不在 P7 范围，请 Cowork 改写）**：`docs/etf-card-schema-v1.md` v1.1-e 两条（月末判定的 `data/calendar/sse-trading-days.csv` → 行情库 `calendar` 表；反事实等权点位的 `data/ledger/ew_daily.csv` → 台账库 `ew_daily` 表）；`docs/etf-rotation-prereg-v1.md` §13.0 的「coverage.csv」→ 行情库 coverage 表（V1 报告随附时可导出）。
- **已处理交易日也进了台账库**（§11 没点名）：`data/jobs/processed-days.txt` 是运行数据，与「结构化数据进 SQLite」同理，改为台账库 `job_days` 表；它本来就该跟着台账走（之前不论 `--db` 是哪个库都共用一个文件）。
- **台账版本号**：P7 只是存储位置变化、记账口径不变，取名 `v1.1-g.1`；P6e-2 落 v1.1-h 时再升 `v1.1-h`。`TERMS_VERSION` 不动（`jobs-daily-v3`）。
- **prereg §13 记内容哈希，不记包文件哈希**：包文件的字节含作业时刻、也随 SQLite 版本变；`content_sha256`（MANIFEST.json 与 build-report 里都有）在同一源库、同一 D、同一 commit 下任何机器都相同。§11 写的是「包的 sha256」，建议改为「包的 content_sha256」；面板同理（`panel_content_sha256`，OOS 锁已记）。
- **coverage 列名 `series_file` → `series_adj`**：文件名不再有意义；V1 报告与 build-report 里引用研究序列的地方改为 `series_code` + `series_adj`。
- **迁移期 CSV 读法**：`prereg_v1/panel.py` 的 `read_table_csv` 与对照测试 `test_panel_db_reads_like_the_old_csv` 按 §11「合并后删」保留；建议放进清理包一起删。
