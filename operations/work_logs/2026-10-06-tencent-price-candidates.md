# 腾讯价格指数全历史候选采集

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 000852 / 000905 年度原响应保全与全历史候选核验
- Timestamp (UTC): 2026-10-06T04:03:42Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮指令；operations/work_logs/2026-10-06-real-source-feasibility.md「Pi 下一包」；main 60196ae

## 检查结果

| 候选（price_only） | 年度窗口 | 裁剪后行数 / 官方日历 | 起止 | 缺日 / 额外 / 重复 / OHLC异常 |
|---|---:|---:|---|---|
| 000852 中证1000 | 22 / 22通过 | 5,282 / 5,282 | 2005-01-04～2026-09-30 | 0 / 0 / 0 / 0 |
| 000905 中证500 | 22 / 22通过 | 5,282 / 5,282 | 2005-01-04～2026-09-30 | 0 / 0 / 0 / 0 |

44个逻辑请求、44次HTTP尝试，全部HTTP200且业务code=0；无403、空年或部分年冒充完整，无重试。身份 `data[symbol].qt[symbol]` 分别为 `['1','中证1000','000852']` 与 `['1','中证500','000905']`；行情取 `data[symbol].day`，原字段顺序 `date,open,close,high,low,原始量`。

按年度请求2005–2025的01-01～12-31，2026硬截止09-30；每个窗口独立保存原文，解析后严格裁到请求窗口。44响应原始合计13,924行，裁掉窗外3,360行，两个完整候选合计10,564行。每年度日期集合与正式calendar对应窗口逐日一致；全历史再次核对日期全集、首尾与21处跨年边界，无缺失/额外/重复。原响应跨窗重叠OHLC没有不一致；OHLC全部正且有限，满足low≤open/close≤high。没有用去重吞掉重复或用邻价补缺。

## 取数与证据索引

已授权并经上包验证的路径（不是原web.ifzq端点的静默替换）：

`GET https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param=sh<code>,day,<start>,<end>,320,qfq`

实际URL编码、UTC获取时刻、HTTP/业务状态、原文文件名、字节数、SHA256、身份与逐年检查均在轻量索引 `operations/work_logs/2026-10-06-tencent-price-candidates-index.json`。原文在 `outputs/data/tencent-price-candidates-20261006/recorded/`，同目录保留requests/attempts/annual-checks/summary/audit、每年及汇总候选JSON与可运行采集检查脚本；不入Git。44响应文件字节数及SHA256全部复核匹配。独立只读review结论approve_with_follow_up：本批全历史与代码/名称复核通过；指出采集脚本最初只断言代码，现已补充名称断言并离线核对44份身份，无重新请求。上包原件不在本服务器，本轮记录自己的原件与时刻/哈希，不冒充重现上包响应字节。

**仅为独立价格指数候选**：qfq请求参数不使指数成为全收益，更不是ETF后复权；原始量字段单位未核定，暂不按既有成交量单位入库。不拼接H00852/H00905全收益close与价格OHLC，不覆盖全收益或coverage，不改正式研究池/选择。即便OHLC全历史通过，口径与正式纳入仍须由编排方冻结，再另包副本验证入库。

正式库SHA256保持 `8fa89a71c2afad92204f0c00a343f031e6108db37e0e76e2b828b41f8f72e0af`，无业务代码或库写入、无收益/指标/研究计算、未开规则/cron。仅提交本页及轻量证据索引，不重打研究包。其他数据阻塞按既有盘点继续，不因这两个候选通过而放行研究。
