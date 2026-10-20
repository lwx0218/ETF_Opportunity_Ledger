# 净值 / 份额 / 折溢价 / 成交额单位 — 来源摸底（2026-10-19）

工作目录：`/workspace/grok-nav-shares-20261019/`  
范围：`data/universe.csv`（dev）中除 T29 外全部执行基金，共 **38** 只。  
取数路径优先级：akshare → 东财/交易所公开 JSON/CSV →（本轮未需要浏览器）。

## 结论一览

| 维度 | 覆盖 | 路径 | 缺口 / 备注 |
|---|---|---|---|
| **单位净值 / 累计净值** | **38/38 ok** | 东财 `api.fund.eastmoney.com/f10/lsjz`（akshare `fund_etf_fund_info_em`） | QDII（513xxx、159509、501018）净值常晚于交易日；当日未出时为暂无，不补 |
| **份额（日频）** | **36/38 ok** | 上交所 ETF 规模日频 27 只；深交所规模日频 9 只 | **501018、511880** 不在上交所 ETF 份额日表 → 日频份额 **暂无**；可用东财「规模变动」季报（亿份）作低频对照 |
| **折溢价** | 方法已定，样例 4 只 | EOD：`(收盘 − 单位净值) / 单位净值`，同日对齐 | **IOPV 不可替代日终折溢价**；净值未出当日不算 |
| **成交量单位** | 全市场统一结论 | 东财 kline `f56` / 腾讯 `day[5]` / akshare「成交量」 | **`volume_unit=unverified`**（接口未标注手/股；禁止按量级猜测） |

## 1. 净值（NAV）

- **接口**：`GET https://api.fund.eastmoney.com/f10/lsjz`
  - 参数：`fundCode`、`pageIndex`、`pageSize`、`startDate`、`endDate`
  - 页面：`https://fundf10.eastmoney.com/jjjz_{code}.html`
- **字段**：`FSRQ`→净值日期，`DWJZ`→单位净值，`LJJZ`→累计净值，`JZZZL`→日增长率，`SGZT`/`SHZT`→申购/赎回状态
- **本轮试取**：窗口约 2026-09-01～2026-10-19；38 只均 HTTP 200，每只约 27–28 行；原始分页 JSON 在 `raw/nav_em_{code}_p*.json`，解析样例在 `samples/nav_{code}.csv`
- **交叉**：与 `fund.eastmoney.com/cnjy_dwjz.html`（akshare `fund_etf_fund_daily_em`）当日/上一日净值列一致（当日净值未披露时显示 `---`）
- **未采用**：基金公司官网逐只爬取（东财已通且可复现）；未登录、无付费墙

## 2. 份额（Shares outstanding）

### 2.1 上交所日频（27/29 SSE 代码）

- **接口**：`https://query.sse.com.cn/commonQuery.do`
  - `sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L`，`STAT_DATE=YYYY-MM-DD`
  - 页面：`https://www.sse.com.cn/assortment/fund/etf/list/scale/`
- **字段**：`SEC_CODE`、`SEC_NAME`、`ETF_TYPE`、`STAT_DATE`、`TOT_VOL`
- **单位**：接口 `TOT_VOL` 为 **万份**；换算为份需 ×10000（与 akshare `fund_etf_scale_sse` 一致）。本包在 `samples/shares_sse_20261016.csv` 同时保留 `TOT_VOL` 与 `基金份额_份`
- **样例日**：2026-10-16（2026-10-17 返回空，已原样存 raw）
- **未覆盖**：`501018`（LOF）、`511880`（货币 ETF）——不在该 ETF 规模表（同日 511 段仅债券类 ETF，无 511880）

### 2.2 深交所日频（9/9 SZSE 代码）

- **列表快照**：`https://fund.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1000_lf` → `当前规模(份)`，单位 **份**
- **日频序列**：`https://www.szse.cn/api/report/ShowReport?CATALOGID=scsj_fund_jjgm&jjlb=ETF`（日期跨度 ≤6 个月）→ `基金规模(份)`
- **样例**：`samples/shares_szse_list.csv`、`samples/shares_szse_daily_sample.csv`（2026-10-01～10-17，9 只均有）
- **备注**：`159732` 深交所简称显示「消费电子ETF华夏」，与 universe「天弘中证消费电子主题ETF」不一致，**身份待核**，本包不改正文名称

### 2.3 低频回退（501018、511880）

- **东财规模变动**：`https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=gmbd&code={code}`
- **频率**：季报；字段「期末总份额（亿份）」
- **样例**：`samples/gmbd_em_501018.csv`、`samples/gmbd_em_511880.csv`（及对照 `gmbd_em_510300.csv`）
- **结论**：日频份额对这两只登记为 **暂无**；季报可用但不进日频折溢价分母相关计算

## 3. 折溢价（Premium / Discount）

- **日终定义（唯一采用）**：  
  `premium = (market_close − NAV_unit) / NAV_unit`  
  仅当 **同一自然日** 的单位净值与收盘价都已取得时计算；缺任一侧 → 当日折溢价 **暂无**（不插值、不用前一日净值顶替）。
- **样例（2026-10-16）** 见 `samples/premium_sample_20261016.csv`：

  | code | close | NAV | premium |
  |---|---|---|---|
  | 510300 | 4.236 | 4.2426 | −0.1556% |
  | 159915 | 2.789 | 2.7903 | −0.0466% |
  | 518880 | 8.554 | 8.5709 | −0.1972% |
  | 511260 | 135.208 | 135.235 | −0.0200% |

- **辅助表**：天天基金场内净值页含「市价」「折价率」列，可作交叉；当日净值未出时为 `---`。
- **IOPV**：盘中实时估值（各行情源常见）**不可**作为日终折溢价替代；若产品需要盘中监控，应单独字段标注 `iopv`，与 EOD `premium` 分列。本轮未把 IOPV 写入交付 CSV（push2 spot 502，未绕过）。

## 4. 成交量 / 成交额单位

- **来源对比**（510300，2026-10-16）：
  - 东财 `push2his` kline：`volume(f56)=37995085`，`amount(f57)=16092791436`
  - 腾讯 `fqkline` day：`volume=37995085`（与东财一致）
  - akshare `fund_etf_hist_em` 将 f56 映射为「成交量」，**文档与字段均未写明「手」或「股」**
- **结论**：`volume_unit=unverified`。量级上 amount/close ≈ volume×100，**暗示**可能为手，但按项目硬边界 **禁止按量级猜测**，故不标注为手或股。
- **成交额**：东财 `f57` / akshare「成交额」为金额（元），本轮未发现歧义；若入库建议字段名 `amount_yuan` 并在 README 写明来源。

## 5. 被拦 / 失败项（已停，未绕过）

| 项 | 现象 | 处理 |
|---|---|---|
| `fund_etf_spot_em` / push2 clist | HTTP 502 Bad Gateway | 停；折溢价改用 NAV+收盘自算 |
| push2 `/api/qt/stock/get` spot | 502 | 停；IOPV 本轮未取到 |
| SSE `STAT_DATE=2026-10-17` | 200 但 result 空 | 原样存 raw；改用 2026-10-16 |
| 501018/511880 日频份额 | 不在 SSE ETF 规模表 | 登记暂无；季报 gmbd 作 partial |

无登录墙、验证码、付费墙。

## 6. 交付文件

| 路径 | 说明 |
|---|---|
| `sources_map.csv` | 38 行：每代码净值/份额/折溢价/成交量来源与 status |
| `manifest.csv` | 每个 raw 原件一行（URL、方法、参数、fetched_at 本机、HTTP、bytes、sha256） |
| `samples/nav_*.csv` | 38 只近期净值解析样例 |
| `samples/shares_sse_20261016.csv` | 上交所份额样例（含本池 27 只） |
| `samples/shares_szse_*.csv` | 深交所列表 + 日频样例 |
| `samples/gmbd_em_*.csv` | 季报份额（501018/511880/510300） |
| `samples/kline_em_510300.csv` / `kline_tencent_*` | 成交量交叉 |
| `samples/premium_sample_20261016.csv` | 折溢价四点样例 |
| `raw/` | 全部原始响应（不入 Git 推送包） |

## 7. 建议的日常取数（本机 cron，非正式作业）

1. 每个 A 股交易日 16:30 后：对 38 码拉 `lsjz` 增量；对 SSE 拉当日 `STAT_DATE` 规模；对 SZSE 拉 `scsj_fund_jjgm` 当日。  
2. 收盘 kline（东财或腾讯，不复权）追加；`volume_unit` 保持 unverified 直至官方口径核实。  
3. 折溢价仅在「净值日期 == 交易日期」时计算并落库。  
4. 501018/511880：日频份额保持暂无；可按季更新 gmbd。

