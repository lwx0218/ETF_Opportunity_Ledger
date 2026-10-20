# ndxtmc-fred — FRED NASDAQNDXTMC（尝试补 2019-01-01～2022-03-20）

## 取数路径
- `GET https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQNDXTMC`
- 另试 `cosd`/`coed` 限定窗口（HTTP/1.1）；官方 observations JSON 需 api_key（未注册，400，未绕过）。

## 结果：**暂无**（缺口窗无点）
| 项 | 值 |
|---|---|
| FRED 全序列有效行 | 1148 |
| FRED 起止 | **2022-03-21** … 2026-10-15 |
| 窗口 2019-01-01～2022-03-20 内行数 | **0** |
| OHLC | 仅 close；open/high/low 空 |

证据：
- `raw/fred_NASDAQNDXTMC.csv`（及同内容的 `*_20190101_20220320.csv` / `*_20050101_20220320.csv`）首条观测均为 `2022-03-21`。
- `raw/PROOF_gap_window_empty.txt`
- `daily_close_gapfill_20190101_20220320.csv` 仅表头（0 数据行）。

## 身份与混用
- FRED `NASDAQNDXTMC` = **收盘指数水平（close-only）**，来源路径 = FRED。
- 与 Nasdaq `HistoryData` OHLC（自 2022-03-21，见 10/16 包）**不要无标签混用**。本包 `daily_close.csv` 的 `source_segment=FRED_NASDAQNDXTMC`。
- 与 10/16 Nasdaq 包重叠段可作交叉核对（先前 20 日两位小数一致）；本包未改任何数值。

## 文件
- `raw/fred_NASDAQNDXTMC.csv` — 主原件
- `raw/fred_NASDAQNDXTMC_20190101_20220320.csv` — 缺口窗请求（仍从 2022-03-21 起）
- `raw/fred_NASDAQNDXTMC_overlap_sample.csv` — 2022-03-21～2022-04-30
- `daily_close.csv` — 全 FRED close
- `daily_close_gapfill_20190101_20220320.csv` — 空（证明暂无）
