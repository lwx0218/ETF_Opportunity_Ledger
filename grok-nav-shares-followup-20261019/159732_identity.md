# 159732 管理人 / 身份核对

核对时刻（本机 Asia/Taipei）：2026-10-19 约 17:20–17:43  
结论基于可复现原件，未臆造。

## 结论（先看这里）

| 项 | 官方（取证） | universe.csv（dev） |
|---|---|---|
| 代码 | 159732 | 159732 |
| 全称 | **华夏国证消费电子主题交易型开放式指数证券投资基金** | 天弘中证消费电子主题ETF |
| 场内简称 | **消费电子ETF华夏** | （隐含天弘） |
| 管理人 | **华夏基金管理有限公司 / 华夏基金** | 天弘 |
| 跟踪指数 | **国证消费电子主题指数** | 研究指数写 931494「中证消费电子主题」 |

**判定：**

1. **SZSE 简称「消费电子ETF华夏」正确**（管理人缩写进简称，不是写错成华夏）。
2. **universe 错误**：把 159732 写成了「天弘中证消费电子主题ETF」——管理人（天弘≠华夏）、指数口径（中证≠国证）都不对。
3. **建议：flag for Cloud Agent 修正 universe**（不要 keep）。至少改：
   - `execution_fund_name` → `华夏国证消费电子主题ETF` / 场内简称 `消费电子ETF华夏`
   - 管理人相关表述去掉「天弘」
   - 评估研究指数：容器若坚持「中证消费电子 931494」，则执行基金不应是跟踪**国证**的 159732；备选列里的 `561600` 在东财检索为「消费电子ETF**平安**」，也不是天弘。东财检索「天弘中证消费电子」**无命中产品**（`em_suggest_tianhong_zhongzheng.json`）。

## 取证摘要

### 1) 东财 F10 基本概况（页面）

- URL: `https://fundf10.eastmoney.com/jbgk_159732.html`
- 原件: `raw/159732/em_jbgk_159732.html`（HTTP 200）
- 解析字段见 `raw/159732/identity_extract.json`：
  - 基金全称：华夏国证消费电子主题交易型开放式指数证券投资基金
  - 基金简称：消费电子ETF华夏
  - 基金管理人：华夏基金
  - 基金托管人：建设银行
  - 跟踪标的：国证消费电子主题指数
  - 业绩比较基准：国证消费电子主题指数收益率

同码检索：`https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=159732`  
→ NAME=`消费电子ETF华夏`，JJGS=`华夏基金`（`raw/159732/em_suggest_159732.json`）。

### 2) 东财 pingzhongdata

- URL: `https://fund.eastmoney.com/pingzhongdata/159732.js`
- 原件: `raw/159732/em_pingzhongdata_159732.js`
- `fS_name="消费电子ETF华夏"`，`fS_code="159732"`

### 3) 深交所基金规模（带代码过滤）

- URL: `https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=scsj_fund_jjgm&TABKEY=tab1&txtDm=159732&txtStart=2026-10-01&txtEnd=2026-10-17&jjlb=ETF`
- 原件: `raw/159732/szse_jjgm_159732_oct.json`（需 Referer `www.szse.cn`，无 Referer 曾 403）
- 样例行：`security_short_name=消费电子ETF华夏`，`fund_code=159732`，`size_date=2026-10-16`，`current_size=201,644.79`（万份口径与本包主表一致）

上一批 C 摸底的列表快照（`samples/shares_szse_list.csv`，已拷入 `raw/159732/`）：

- 基金管理人 = **华夏基金管理有限公司**

### 4) 华夏基金产品站

- `https://www.chinaamc.com/fund/159732/index.shtml` → HTTP 200，页面含代码 159732（`raw/159732/chinaamc_product_159732.html`）
- PCF 直链 `getPortfolioCompositionFile.do?fundcode=159732` → 404（已停，未绕过）

### 5) 未采用 / 失败的接口

| 尝试 | 结果 |
|---|---|
| `api.fund.eastmoney.com/f10/jjgk?fundCode=159732` | ErrCode 404 |
| `fundmobapi.../FundMNBasicInformation?FCODE=159732` | ErrMsg 网络繁忙 |
| SZSE 无 Referer | 403 |
| 东财检索「天弘消费电子」「天弘中证消费电子」 | 无天弘同名 ETF；出现的是华夏/招商/平安/鹏华等消费电子产品 |

## 与 universe 的双重偏差（供 Cloud Agent）

`data/universe.csv` T12 行（dev）：

- `execution_fund_code=159732`
- `execution_fund_name=天弘中证消费电子主题ETF` ← **错**
- `research_index_code=931494`（中证消费电子主题）
- `execution_alternatives=561600`（东财现称为消费电子ETF**平安**，非天弘）

官方 159732 跟踪的是**国证**消费电子主题，不是中证 931494。修正名称/管理人之外，是否继续用 159732 作为「中证消费电子」容器的执行基金，需要产品侧另做映射复核（本 followup 只核身份，不改 universe 文件）。

## 推荐动作

**flag for Cloud Agent to fix universe**（不要 keep 现状）。

建议改法（由 Cloud Agent 在 dev 落地）：

1. 将 `execution_fund_name` 改为与官方一致的华夏国证消费电子主题 ETF 名称/简称。
2. 在备注中写明管理人=华夏；去掉天弘。
3. 复核 T12 研究指数 vs 执行基金跟踪指数是否同族；若必须中证 931494，另选精确跟踪该指数的 ETF，而不是硬改 159732 的指数属性。
