# 真实行情来源实取与交叉核对

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 为 Pi 全历史采集寻找并验证真实数据路径
- Timestamp (UTC): 2026-10-05T17:27:00Z
- Owner: Faye
- Route: review-only
- Source of truth: Owner 2026-10-06 01:18（北京时间）指令；operations/planning/2026-10-06-parallel-data-and-product.md；本轮公开来源原响应

## 结论

中证1000/中证500的腾讯价格指数路径已取得完整年度 OHLC 样本并通过官方日历核验，可交 Pi 扩展全历史候选采集。黄金、国债、海外也取得真实原文，但各有必需字段或日期/数值问题，尚未作为合格策略输入放行。所有采集均独立于正式库；未计算收益、信号或回测，未改策略、研究池与正式序列选择。

### 中证价格指数：可进行全历史候选采集

真实请求（GET；参数中的逗号允许 URL 编码）：

```text
https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param=sh000852,day,2005-01-01,2005-12-31,320,qfq
https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param=sh000905,day,2011-01-01,2011-12-31,320,qfq
```

响应身份在 `data[symbol].qt[symbol]`，行情实际在 `data[symbol].day`，每行前六字段为 `date, open, close, high, low, 原始量字段`。第六字段的单位尚未核定，本轮只验证OHLC，不直接按既有成交量单位入库。这是价格指数，`qfq` 请求参数不能把它变成全收益或 ETF 后复权。

| 样本 | HTTP | 原始行数 / 窗口内行数 | 日历与 OHLC 检查 | 原响应 SHA256 |
|---|---|---|---|---|
| 000852，2005 年 | 200 | 242 / 242 | 与正式官方日历逐日一致；无缺失、额外、重复；OHLC 正数且高低包络有效 | `558802d6db5f52c802509f5d25028a62197f6b9ca217f6c5868936a48b011361` |
| 000905，2011 年 | 200 | 320 / 244 | 同上；原响应含 2010 年记录，须裁剪请求窗 | `c11ee075ebc35a47e051a812ee8b5897dfbf86551dd9a1ecca828bbeaff4c06b` |

与 CSI 官方 `https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=<code>&startDate=<YYYYMMDD>&endDate=<YYYYMMDD>` 交叉核对：000852 的 2005 年初9日、2026-09-14～30的12个重合日，OHLC全部一致；2015年初10日仅2015-01-12开盘差0.01（CSI6098.82，腾讯6098.81）。000905的2011年初8个重合日两项差0.01，腾讯另返回CSI该短窗缺少的2011-01-14。差异保留，不擅自选择有利值。CSI价格版本也出现截止日未返回，不能仅靠请求成功判断日期齐全。

取证 agent 保存原文及检查结果后，编排方直接读取原响应，独立复核上述两份年度哈希、日期全集、高低包络，以及000852近期和2015年逐字段差异。正式库当前没有000852/000905/000300价格序列，不存在重复恢复这些已入库序列的问题。

**Pi 下一包**：仅扩展000852、000905，从2005年到2026-09-30，按年度请求（末年硬截止），每次保存原文/URL/时刻/状态/哈希，解析后裁剪；逐年核日历、重叠边界、重复及OHLC，再汇总。403停止该来源，不以空年或部分年冒充完整。先落独立候选目录与清单，标明 `price_only`，与H00852/H00905全收益材料分开；本包不改正式库或coverage、不自动替换研究输入。全历史通过后再由编排方冻结选择，安排正式入库。

原件暂存：`outputs/source_feasibility_csi_20261006/`，入口 `README.md`、`annual_validation.json`、`crosscheck.json`。本文件记录的是小样通过，全历史与其他指数尚未验证。

### 黄金：官方 OHLC 路径存在，待解决源数据异常

真实请求：`POST https://www.sge.com.cn/graph/Dailyhq`，表单 `instid=Au99.99`，字段顺序 `date, open, close, low, high`。HTTP200，97,215字节，SHA256 `79788cd1e6502e3c31e4cceaf05596f4d903f82650ac80f971a5771c869ea655`。

取得2016-12-19～2026-09-30共2,375行，无NULL、无重复，但17行close超高低范围，分布2017-02-10～2018-04-02；不能自动修平。2023-12-29、2026-09-15与官方日报OHLC一致；2008-09-05官方日报原文也已取得（open179、high179、low175.3、close176.9）。

官方入口：`https://www.sge.com.cn/sjzx/mrhqsj`；旧样本 `https://www.sge.com.cn/sjzx/mrhqsj/509694?top=789398439266459648`；2023样本 `https://www.sge.com.cn/sjzx/mrhqsj/10005759`；近期日查询 `https://www.sge.com.cn/sjzx/quotation_daily_new?end_date=2026-09-15&start_date=2026-09-15`。

该源不是A股日历：2024-02-09是SGE真实交易日，官方公告 `https://www.sge.com.cn/jjsnotice/10005807` 已确认；相对A股日历少2018-03-29、2020-10-28、2021-03-17，仅作待核日期。包含前工作日晚盘至当日15:30，graph没有成交量。需核对17行异常、三日及历史分页，再决定日历和可用时点；目前不正式入库，也不因找到OHLC就自动替换518880后复权。

### 国债：正确再投资代码已证实，仍缺 OHL

官方 `https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H11077factsheet.pdf`（2026-08-31版第2页）与实取响应确认：H11077为上证10年期国债指数，其利息及再投资版本是 **N11077**。当前候选列表需后续据此纠正，不能把猜测代码当成已核实身份。

CSI请求 `indexCode=N11077&startDate=20260914&endDate=20260930` 返回12行，名称明确“上证10年期国债指数（利息及再投资）”，但OHL全部NULL，仍不满足策略。新浪返回511260的5次现金分红记录，仅属构造标准hfq的候选材料，事件完整性及基金公告尚未核验；518880仅返回占位记录，不证明无历史分红/折算。

黄金/国债原件和检查：`outputs/source-discovery-gold-bond-20261006/{request-index.json,validation.json}`。

### 海外：取得官方交叉核对源，未取得完整 OHLC

- **NDXTMC**：`POST https://indexes.nasdaq.com/Index/HistoryData`，表单 `id=NDXTMC&startDate=2026-09-21&endDate=2026-09-30&timeOfDay=EOD`，8行HLC，收盘与 `https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQNDXTMC&cosd=2026-09-21&coed=2026-09-30` 按两位小数8/8一致。没有Open。官方 `https://indexes.nasdaq.com/docs/Calculation_Manual_Equities_and_Commodities.pdf` 第5页说明SOD是前日收盘经公司行为调整，不能当成当天成交开盘。
- **HSTECH**：官方 `https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/v1/product-data/pub/indexes/metadata/v2?data=valueHistoryPub&indexCodes=02083.00&language=eng` 返回1229条close，2021-10-04～2026-10-05，无重复/缺值，身份明确，缺全部OHL。响应自动包含研究截止后原值，仅用于来源核验，后续研究仍硬截止2026-09-30。
- Yahoo的 `HSTECH.HK` chart API实际HTTP200但 `timestamp=null`、`quote={}`，不能将网页可见历史或HTTP成功当作API历史可用。ADVFN返回403，已停止。

海外取证：`outputs/data/source-feasibility-overseas-2026-10-05/index.json` 与 `outputs/source-feasibility-hstech-20261006/index.json`。本轮没有更换成NDXT等近似指数。

## 保全与后续

原响应与详细索引保留在本轮工作目录的outputs，未把重型原件提交Git；上列请求可供Pi复现，重新获取须记录自己的时刻和哈希，不要求含实时元数据的响应字节与本轮相同。轻量发现入Git。正式库SHA256仍为 `8fa89a71c2afad92204f0c00a343f031e6108db37e0e76e2b828b41f8f72e0af`。

优先让Pi扩展已通过小样的两个价格指数候选；编排方继续黄金异常与ETF分红/复权路径。产品前后端开发按并行计划进行，不等待这些来源全部解决。
