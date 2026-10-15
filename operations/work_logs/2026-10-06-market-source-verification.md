# 行情异常原件与腾讯成交量单位核验

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 首批纠偏执行单第四节 · Pi 并行只读取证
- Date: 2026-10-06（基线）；短窗采集 11:12:35～11:12:42
- Owner: Faye
- Route: direct-execute
- Source of truth: operations/planning/2026-10-06-observation-and-pages.md §4；Owner 本轮指令
- Baseline: `ae7b63d89967267bbb4d1f1cb0ea077fb86f56a7`

## 结论先行

**95 行库存异常全部保留；未找到四份 run 2 写库请求哈希匹配原件，不能宣称写库原字段已闭环。** 78 行有其他采集的源字段旁证，17 行仍无行级旁证。腾讯执行 ETF 日线第六字段单位仍为 **`unverified`**。本轮只取证，不修价、不删行、不换源、不写回量、不修改字段资格。

| 库内序列 | 异常行 | high＜low | 匹配写库原件 | run 1 原字段旁证 | 本轮短窗旁证 | 无任何行级旁证 |
|---|---:|---:|---:|---:|---:|---:|
| 399006/raw/tencent_index | 8 | 0 | 0 | 8 | 8 | 0 |
| BRENT/raw/yahoo（实际 BZ=F） | 69 | 6 | 0 | 69 | 10 | 0 |
| 510880/raw/tencent_etf | 18 | 0 | 0 | 0 | 1 | 17 |

本轮数量与执行单一致。异常依据为原存储值的 `high < max(open,close)`、`low > min(open,close)` 或 `high < low`，未引入容差。原件、旁证、未知不能互换：78 行源字段在其它真实采集中复现，不等于这 78 行找到了写库原件；95 行写库输入链仍未完全证明。

## 写库请求与原件搜索

逐行清单见 [95 行异常 CSV](2026-10-06-market-source-verification.csv)，请求/文件/字段/单位索引见 [JSON](2026-10-06-market-source-verification-index.json)。CSV 的 `write_request_id`、`probe_request_id`、`new_short_request_id` 连接索引，不重复整份响应。

| 异常日期组 | 写库请求 | 写库响应 SHA256 | 已核 probe 旁证（不是写库原件） |
|---|---|---|---|
| 399006，2010 年 7 行 | run2/seq140 | `7524e1cc532366004f89418d5e89894a1dfab7502b990a04d4eaa1adad8f63fe` | run1/seq64，`4715927eb228.body` |
| 399006，2015-03-27 | run2/seq144 | `5b478193c534a90416c43e02747d1ca1be87ce34515d1f2d4b641564055d6309` | run1/seq68，`c3609cd6c56e.body` |
| BRENT，69 行 | run2/seq413 | `e99cd69858443c3c99f760ad08a5023cf9d2d8f06f60852f3195dfa6310eeeac` | run1/seq121，`75ed64377f29.body` |
| 510880，18 行 | run2/seq839 | `f750ab71a4ae591c09c77f785f5dd6c5ae22cb31fa42878aba5d694ef4c417a4` | 未找到对应历史 probe |

run 2 共 1,036 个 requests，`file` 均为空。检索本项目文件及全部 `outputs/`，排除 `.git/.pi/.venv/node_modules/__pycache__` 与符号链接；4,842 个文件经长度筛选、候选再算 SHA256，未发现四个写库哈希匹配原件。**这是本项目搜索范围内未找到，不是已搜索服务器全盘。** 三份 probe 的实际长度和哈希均匹配 run 1 登记，分别为 `fa1899…fe40c`、`46184f…f5bcc`、`59ea1b…ca26fe2`，与 run 2 哈希不同，不能因同 URL 当作同一原件。

关联依据是代码/来源、请求 symbol/窗口、run 2 作业及原执行代码（`5fcec9dfc78390611c56ebd07681db6d816a8f71`）。`bars.fetched_at` 是整序列写入时刻（399006 15:03:38Z、BRENT 15:13:10Z、510880 15:27:51Z），不是 `requests.fetched_at`。两个时刻在 CSV/索引分别保留，不用于宣称历史当时可得。

旧 `http.get` 没有保存数字 HTTP 状态，历史索引 `http_status=null`；请求 error 为空不是补写 200 的依据。

## 原字段与解析裁定

- **旁证已证明的源字段异常：** run 1 三原响应的 77 个异常日期，与库存 OHLCV/amount 逐字段一致；用原执行提交的纯解析路径、mock 已保全响应离线复验，77 行一致，未见列顺序/时区/解析转换差异。这里证明的是旁证自身存在异常，不能代替缺失的 run 2 响应。
- **399006 的七条 2010 年小偏差：** 原文 open/close 的三位小数与 high/low 较粗值存在 0.001～0.004 的包络差，短窗再次完全复现。形态与精度差异一致，但未取得上游精度合同，不授权容差、扩价或修正。2015-03-27 则 `high=low=2326.418`，`open=2274.677`、`close=2323.819`，不能一起用小数精度解释。
- **BRENT：** 69 行由 Yahoo `BZ=F` 原字段旁证复现。其中 high＜low 的六个日期为 2009-12-23、2009-12-24、2010-01-04、2010-01-05、2010-01-07、2010-04-15。短窗覆盖其中前五条；2010-04-15 只有历史 probe 旁证，未新增采样。六条高低倒置不能统一归因为结算价语义；其余 close 越界也缺经济字段定义，根因仍未知。不得转成布伦特现货或另一个合约。
- **510880：** 本轮只复验 2010-01-12，原文 `[date,open,close,high,low,volume]` 为 `["2010-01-12","2.735","2.782","2.780","2.700","880106.740"]`，与库存完全一致，close＞high 在源字段出现。另 17 行没有本轮行级源旁证，不能借这一行宣称全组已经结案。

## 新短窗（仅旁证）

六个明确授权窗口各请求一次，**6 次请求/6 次尝试，实际 HTTP 200，无重试**，原件全部保全在全新 `outputs/market-source-verification-20261006/short-windows/`，未覆盖旧 `recorded/`。

| symbol | 窗口 | 窗内行数 | 库存异常日期数（全部原字段一致且仍异常） |
|---|---|---:|---:|
| sz399006 | 2010-05-31～08-06 | 45 | 7 |
| sz399006 | 2015-03-23～03-31 | 7 | 1 |
| sh510880 | 2010-01-11～01-15 | 5 | 1 |
| BZ=F | 2007-12-20～12-28 | 6 | 1 |
| BZ=F | 2009-12-21～2010-01-15 | 18 | 8 |
| BZ=F | 2015-07-13～07-20 | 6 | 1 |

19 条异常得到新增采集旁证，均不是历史写库原件。腾讯仍走登记的 `fqkline/get`、空复权参数；Yahoo 日期按原响应交易所时区映射，UTC 请求边界与交易所日不混用。未请求其它行情窗口或新的 source。

## 腾讯执行 ETF 量单位

**适用对象必须同时匹配：** `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get`、执行 ETF、`day[i][5]`、复权参数留空。不以非 NULL/正量、价格乘量或跨源数值比例认证。

| 证据层 | 已取得内容 | 本轮判定 |
|---|---|---|
| 现有本地声明 | intake §5（line121）、data-layer line75、framework line210、sources.py line6 写“手”；解析为 day 第六字段 | 项目合同/实现声明，单列保留；不是新取得的源级单位证明 |
| 提供方 JS 旁证 | [腾讯 ETF 页面](https://gu.qq.com/sh510880) 引用 [图表 JS](https://st.gtimg.com/quotes/hs-fund/zxgweb-chart-5878585c4a61.js)；`STOCK_UNIT` 将 sh/sz/jj 标“手”，第六字段进入 volume | JS 构造的是 `newfqkline/get` / `newkline/newkline`，不是本库 `fqkline/get`；没有跨接口单位一致性保证，不能认证 |
| 第三方包装文档 | [AKShare stock_zh_a_hist_tx](https://akshare.akfamily.xyz/data/stock/stock.html) 当前输出 volume 声明“已统一为股”，对象为 A 股上市公司 | 包装后输出单位≠腾讯原字段单位，且对象不覆盖执行 ETF；不反推“手/股/份” |
| 已取得精确上游定义 | 无 | **unit=unverified**；不允许量图认证或写回指数候选量 |

四份定义相关 HTTP 原文已保存 URL、UTC、实际状态、长度、SHA256、路径与原文位置；第四份 AKShare 源码实际只涉及实时接口，明确排除。一次多角度检索、四份材料 GET，无新 ETF 行情请求。原响应/大文档不入 Git，索引只保留必要证据元数据。

优先复用 run 1 的近期原件：当前 37 个 retained/flagged 容器对应的 37 个执行 ETF，各 2026-08-16～09-30 窗内 **32 行**，共 1,184 行；原文件 bytes/SHA256、身份、空复权、官方交易日集合、正有限 OHLC/包络、正量及库存 OHLCV 一致性均通过。**这只是近期 probe 静态旁证；不是全历史通过、不是量单位认证。** 本轮没有把执行单既有 07-01～09-30 各 65 行结论冒充新复验。

## 保全与交付

- 前后正式行情库 SHA256 均为 `448c8f1f3a9568b7cde5ebcf8a4dc5eb8392ca59c9681cea938235430ef8d150`；`integrity_check=ok`。正式 `data/ledger.sqlite` 原本不存在，未创建。
- 未执行 probe/backfill/update、扫描、build、characterize/design/oos/rolling；不重启 8765 或 8000，不改页面、业务源码、coverage/universe、量字段、规则或 cron。
- 可复验：`PYTHONPATH=. outputs/s1-venv/bin/python -B outputs/market-source-verification-20261006/check_evidence.py`。纯离线核验原执行解析、文件哈希、引用位置与库保全。独立只读 review `sa-9df0dc57` 为 **approve / OK**，已独立验证 SQL/CSV、77 行原解析、19 行短窗、单位引用及 37×32 近期行；无 findings。
- 已查看范围：95 条异常、三份历史 probe 对应原字段、六个批准短窗、37 ETF 近期原 OHLCV、官方日期及四份单位定义材料；仅描述性取证，无策略效力、收益或买卖结论。
- Git 仅提交本页、95 行 CSV 与轻量 JSON 索引；完整原件、脚本、日志与检查产物留在忽略的 `outputs/`。

## 下一步归属

由编排根据原件/旁证/未知三层证据裁定字段资格或另开修复任务。run 2 原件缺失、510880 其余 17 行、BRENT 语义与精确 ETF 量单位定义仍未解。本轮不把未知变成修价建议，不将“手”旁证提升为认证，不改任何旧研究修整政策。
