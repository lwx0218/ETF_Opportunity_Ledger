# grok-sources-20261019

补缺取证包（相对 2026-10-16）：T16 腾讯不复权+后复权、T36 FRED 缺口窗、T38 HSTECH 免费再探。

交付日：2026-10-19。不改仓库代码；不推 GitHub（由父代理推分支）。raw 留本机；入库交付 README + manifest + 解析 CSV。

## 总览

| 数据集 | 路径 | 覆盖 / 行数 | 缺口 / 异常 | 被拦 |
|---|---|---|---|---|
| 518880-tencent | 腾讯 newfqkline 不复权（param 末空） | 2013-07-29…2026-10-19，**3213** 行 OHLC+量额 | 缺 2013-07-18～07-26（腾讯无点）；volume_unit=**unverified**；OHLC 异常 0 | 东财 SSL EOF |
| ndxtmc-fred | FRED `NASDAQNDXTMC` CSV | FRED 全序列 2022-03-21…2026-10-15，1148 close | **2019-01-01～2022-03-20 暂无**（0 行） | observations API 需 key（未注册） |
| hstech-gap | 恒指官方 API/页再探 | 免费 valueHistoryPub 仍自 ~2021-10-15 | **2020-07-27～2021-10-11 正式暂无** | 付费订购未下单；部分 400/404；TLS 偶发 EOF（`-k` 取到公开 JSON） |

## 取数路径摘要
- **A1**：腾讯 `newfqkline` / `fqkline`，空复权标志 = 不复权；按年拉取后按 date 去重合并。
- **A2**：FRED `fredgraph.csv?id=NASDAQNDXTMC`（HTTP/1.1）。
- **A3**：仅恒指公司 / HKEX 公开入口；无第三方。

## 后复权（518880）
见 `518880-tencent/README.md`。折算比 0.37761358 @ 2013-07-24；本包无折算前点 → back_adj 与 unadj 数值相同。

## 如何复现
各子目录 README + `raw/_fetch_log.txt`。`manifest.csv` 含每个原件 URL/方法/参数/时间/状态/字节/SHA256。
