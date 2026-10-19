# 518880-tencent — 华安黄金 ETF 腾讯不复权日线 + 后复权

## 取数路径
- **主路径**：腾讯财经 `newfqkline`（`proxy.finance.qq.com/ifzqgtimg/...`）
- **接口**：`GET https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?_var=kline_day&param=sh518880,day,{start},{end},800,`
- **复权参数**：`param` 末段**留空** = **不复权**（响应键 `day`）。对照：`qfq`→`qfqday`，`hfq`→`hfqday`。
- **交叉探针**：`web.ifzq.gtimg.cn/appstock/app/fqkline/get` 同参（2013 年一致）；东财 `push2his` SSL EOF 失败；新浪仅作近期对照（未入库）。
- **字段顺序**（不复权 `day` 行）：`[date, open, close, high, low, volume, {}, amp, amount, ...]` → CSV 重排为 `date,open,high,low,close,volume,amount`。

## 覆盖
| 项 | 值 |
|---|---|
| 行数 | 3213 |
| 起止 | 2013-07-29 … 2026-10-19 |
| OHLC 异常（收盘/开盘越出高低） | 0 |
| amount | 全行有值 |

## 缺口
1. **上市首周～折算停牌**：产品 2013-07-18 上市，折算生效日 2013-07-24；腾讯不复权最早仅 **2013-07-29**（折算后复牌）。2013-07-18～2013-07-26 腾讯无点，**不补、不插值**。
2. 日历空隙 >10 天仅见长假（春节等），未单列为数据缺失。

## 成交量单位
- **`volume_unit=unverified`**。未核实「手」或「股」。新浪同日 volume 约为腾讯约 100 倍（仅观察，不作定论）。`amount` 单位亦 **unverified**。

## 后复权算法（可逐行复现）
事件来源：`events_share_split_ref.csv`（复制自 `grok-sources-20261016/518880-distributions/events.csv`）  
唯一事件：`ex_date=2013-07-24`，`split_ratio=0.37761358`（份额折算：新份额 = 旧份额 × 比例）。

对 `daily_unadj.csv` 每一行：
```
if date < 2013-07-24:
    adj_factor = 0.37761358
    open/high/low/close = unadj * adj_factor   # 六位小数写出
else:  # 含折算日当日及之后
    adj_factor = 1
    OHLC = unadj 原样
volume、amount：不调整（约定不明）
```
本包腾讯序列全部 `date >= 2013-07-29 > 2013-07-24`，故 **`daily_back_adj.csv` 与不复权 OHLC 数值相同**，`adj_factor=1` 全列。算法已实现，若日后补到折算前不复权点可直接复用。

**与腾讯原生 `hfq` 的区别（勿混）**：腾讯 `hfqday` 在折算**之后**把价格乘以 0.3776…（把近期压到早期尺度）。本包按任务约定是「折算**前**乘比例、之后不变」（对齐当前未复权价尺度）。二者相反，已用探针 JSON 保留。

## 身份
- 本序列为 **ETF 场内成交价**（不复权 / 按上述规则后复权），**不是**上金所 Au99.99，也不是价格指数。
- Au99.99 未在本包重新取数。

## 文件
- `raw/tencent_newfqkline_unadj_YYYY.txt` — 按年拉取原件（空复权）
- `raw/tencent_fqkline_unadj_2013.json`、`raw/probe_*.json` — 对照
- `raw/sina_kline_datalen1023.json` — 仅近期，未并入主 CSV
- `daily_unadj.csv` / `daily_back_adj.csv`
- `events_share_split_ref.csv`
