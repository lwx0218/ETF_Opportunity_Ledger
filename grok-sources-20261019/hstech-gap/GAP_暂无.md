# HSTECH 缺口正式登记：暂无

## 缺口区间
**2020-07-27（上市）～ 2021-10-11** — 无免费官方日线水平可入库。

## 本次（2026-10-19）再探结论
1. **免费公开 API `valueHistoryPub`**（indexCodes=`02083.00`）返回 close-only **1231** 点，本次为 **2021-10-15～2026-10-16**（约滚动 5 年窗；10/16 包曾为 2021-10-12～2026-10-15）。**缺口窗内 0 行**。
2. 带 `startDate`/`endDate` 的 valueHistory 变体 → **HTTP 400**（COMMON_0406）。
3. 其它 `data=` 名（valueHistory / valueHistoryEod / indexLevels / dailyClose）→ **400**。
4. **付费** `historicalDataOrderList` → 200，元数据含 DAILY、effectiveDate 2020-07-01、price 1000 HKD；**未下单、未付款**。
5. `dailyReport` 目录仅近月文件；GCS `idx_27Jul20.csv` / `idx_11Oct21.csv` / `idx_15Oct21.csv` → **404**。
6. HKEX 产品页 / 标题检索页无该段日线 CSV；部分深链 404；SPA 壳页面无嵌入历史序列。

## 未使用
Yahoo / Investing / 东财等第三方。不绕过付费墙。

## 官方免费序列现状
免费可得仍大约自 **2021-10-12～2021-10-15**（滚动）起；**2020-07-27～2021-10-11 正式登记为「暂无」**。

原件与 HTTP 结果见 `raw/_fetch_log.txt` 与 `raw/`。
