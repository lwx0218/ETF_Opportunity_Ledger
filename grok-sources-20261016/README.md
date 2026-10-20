# grok-sources-20261016

数据取证包（官方来源原件 + 可复现 CSV）。不修改行情数值；缺字段留空；异常行原样保留。

交付日：2026-10-16。取证助手：Grok Bot（自有电脑/浏览器）。不改仓库代码。

## 总览

| 数据集 | 覆盖 | 行数/事件 | 缺口 / 异常 | 被拦 |
|---|---|---|---|---|
| 518880-distributions | 2013-07-18 上市以来 | 1 次份额折算 | 无现金分红；华安分红栏目 totalCount=0 | 无 |
| 511260-distributions | 2017 上市以来 | 1 次÷100 折算 + 5 次现金分红 | 2018–2024 无现金分红（有检索页证明） | 无 |
| ndxtmc | 2022-03-21 → 2026-10-15 | 1148 日 | 无开盘价/成交量；Close 字段为空，用 Value 作 close | 无 |
| hstech | 2021-10-12 → 2026-10-15 | 1231 日（仅收盘） | **免费缺口** 2020-07-27～2021-10-11；开高低全缺 | 付费历史数据下单页（未下单）；部分查询 HTTP 400/404/504 |
| sge-au9999 | 2016-12-19 → 2026-10-15 | 2381 日 | 17 行收盘价超出高低价（见 anomalies CSV） | 无 |

## 1. 518880-distributions（华安黄金 ETF）

- **事件**：仅 2013-07-24 基金份额折算，折算比例 `0.37761358`（见上交所结果公告 PDF）。无现金分红。
- **原件**：`raw/sse_2013-07-24_*.pdf`、`raw/sse_2013-07-26_*.pdf`；华安同文 HTML；产品页「历史分红」表与空分红栏目 HTML；上交所关键词查询 JSON（分红/拆分等为空，折算=2）。
- **events.csv**：1 行，指向结果公告 PDF。
- **无分红年份**：不是逐年「无分红」列表；证据是产品页历史分红仅一行拆分，以及 `list/631/518880` totalCount=0，上交所分红类查询 total=0。

## 2. 511260-distributions（国泰上证10年期国债 ETF）

- **折算**：2017-08-04，份额变为折算前的 1/100（`split_ratio=0.01`）。
- **现金分红**（公告为 **元/10份**；`events.csv` 的 `cash_per_unit` 已换算为 **元/份**）：

| 除息日 | 权益登记日（场内） | 元/份 | 公告日 | raw |
|---|---|---|---|---|
| 2025-09-23 | 2025-09-22 | 1.360 | 2025-09-18 | gtfund-fenhong-20250918.pdf |
| 2025-12-26 | 2025-12-25 | 0.8330 | 2025-12-23 | gtfund-fenhong-20251223.pdf |
| 2026-03-25 | 2026-03-24 | 0.6711 | 2026-03-20 | gtfund-fenhong-20260320.pdf |
| 2026-06-25 | 2026-06-24 | 1.2686 | 2026-06-22 | gtfund-fenhong-20260622.pdf |
| 2026-09-18 | 2026-09-17 | 1.2747 | 2026-09-15 | gtfund-fenhong-20260915.pdf |

- 合计约 **5.4074 元/份**（= 54.074 元/10份）。上交所镜像 PDF 亦在 `raw/`。
- **2018–2024**：国泰产品公告检索「分红」仅上述 5 条；「拆分」「收益分配」无行；legacy 分红页写「暂无分红」。

## 3. ndxtmc（Nasdaq-100 Technology Sector Total Return / NDXTMC）

- **来源**：`POST https://indexes.nasdaq.com/Index/HistoryData`，`id=NDXTMC&timeOfDay=EOD`，按年分文件 `raw/ndxtmc_YYYY.json`（2005–2021 年响应为空数组，已保留）。
- **字段**：High/Low/Value；`Close` 恒为 null；无 Open/Volume。`daily.csv`：`close`←`Value`，`open`/`volume` 空。
- **起止**：2022-03-21 … 2026-10-15，1148 行。
- **FRED 抽查**：`raw/fred_NASDAQNDXTMC.csv`；`fred_crosscheck_20.csv` 抽 20 日，按两位小数 **0 处不一致**。

## 4. hstech（恒生科技指数 HSTECH / 02083.00）

- **免费可得**：`valueHistoryPub` → `raw/hstech_valueHistoryPub_api.json`，仅 `date,close`，2021-10-12 … 2026-10-15，1231 行 → `daily.csv`（开高低量空）。
- **缺口**：上市日 2020-07-27 至 2021-10-11 **无免费官方日线**。月度资料、日报目录、factsheet 不含该段日线；历史数据为付费订购（未付款、未绕过）。证据页与 400/404/504 说明在 `raw/`。
- **未使用**第三方聚合源。

## 5. sge-au9999（上金所 Au99.99，可选）

- **来源**：`POST https://www.sge.com.cn/graph/Dailyhq`，`instid=Au99.99` → `raw/sge_Dailyhq_Au9999.json`。
- **数组字段推断**：`[date, open, close, low, high]`（唯有此映射使 2017-02-10～2018-04-02 恰好出现 **17** 行「收盘价超出高低价」）。
- **daily.csv**：2381 行，2016-12-19 … 2026-10-15；`volume` 空。
- **异常**：`anomalies_close_outside_hl.csv` 列出 17 行，**未修改**原值。

## 如何从原件复现 CSV

### 518880 / 511260 `events.csv`
从对应 `raw/*.pdf`（或同文 HTML）人工读取：除息日、权益登记日、每份金额或折算比例、公告日、标题、URL；`cash_per_unit` 对 511260 = 公告「元/10份」÷10；缺项留空。

### ndxtmc `daily.csv`
对每个 `raw/ndxtmc_YYYY.json`：读 `aaData[]`；`TimeStamp` `/Date(ms)/` → UTC 日历日（与 FRED `observation_date` 对齐）；`high`←High，`low`←Low，`close`←Value（Close 为 null），`open`/`volume` 空。

### hstech `daily.csv`
读 `raw/hstech_valueHistoryPub_api.json` → `data[0].valueHistory[]` 的 `date`/`close`；其余列空。

### sge-au9999 `daily.csv`
读 `raw/sge_Dailyhq_Au9999.json` → `time[]`：`[date, open, close, low, high]` → CSV 列 `date,open,high,low,close`（high/low 对调列位置，数值不改）；`volume` 空。

## manifest.csv

每个原始文件与派生 CSV 一行：`dataset,file,url,method,params,fetched_at,http_status,bytes,sha256,note`。入库前请按 sha256 核对 `raw/`。
