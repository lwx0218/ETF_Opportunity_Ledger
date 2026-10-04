# S1 数据交付 · 2026-10-04

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: S1 行情保全、官方日历导入、提交与来源锚定
- Timestamp (UTC): 2026-10-04T10:05:21Z
- Owner: Faye
- Route: direct-execute
- Source of truth: 本轮 Owner 指令；`operations/planning/2026-09-29-replan-three-lanes.md` §4/8/11/13；AGENTS.md

## 结果

| 项目 | 交付 / 限制 |
|---|---|
| 研究行情 | 37 个面板容器：有数据 9、失败 28；仅表示取数成功，不代表满足研究输入要求 |
| 执行行情 | 38 条成功、0 失败（含现金，剔除保险）；均截至 2026-09-30 |
| 库 | bars 136,539 行、48 条 `(code, adj)` 序列；行情范围 2000-01-03 至 2026-09-30 |
| H00300 | 0 行，CSI HTTP 403；**阻塞后续研究**，不能用价格指数或 ETF 顶替全收益基准 |
| 恒生科技 | seed / coverage / requests 已使用 `^HSTECH`；实际 Yahoo 请求 404，无研究行情。不是只改代码未抓取，也不能宣称修正后取数成功 |
| 官方日历 | 目标 2005-01-01 至 2026-12-31；实存 2005-01-04 至 2026-12-31，5,343 个交易日；截止后首日 2026-10-08 |
| 完整性 | `integrity_check=ok`，`journal_mode=delete`，无 `-wal/-shm/-journal`；预检 package + verify 通过 |
| 2027 | monthList 2027-01 返回空；未检索到正式年度休市通知，待补、不阻塞 S1 |

## 本次操作与证据

- 核查原 runs：2026-10-02 probe/backfill 均完成，研究默认 `start=2000-01-01`、`exec_start=null`。保留全部已有取数结果，不重复已记录失败、不调晚起点。与写前备份双向 EXCEPT 核对：bars / coverage / requests 均零差异。本轮新增 calendar run 3。
- CSI 多数研究序列 HTTP 403；黄金后复权东财断连；NDXTMC 免费源无数据，既有 Nasdaq 官方历史页检查保留，不用 ^NDXT 替代。9 条可得研究序列为 H00852、399006、399998、BRENT、H20606、H00015、NDX、^SP500TR、N225。H00852/H20606/H00015 缺 OHLC，成交量等缺项仍按 coverage 登记，交下游判断，未填造。
- 日历源：`https://www.szse.cn/api/report/exchange/onepersistenthour/monthList?month=YYYY-MM`。逐月验证 264 个月的自然日集合、重复、开市标志与周末约束；只导出官方 `jybz=1`。原响应与 URL/时刻/哈希记录在 `outputs/calendar/`，离线复核 `python outputs/calendar/validate_s1_calendar.py`，结果 `s1-calendar-validation.json`。
- monthList 唯一自然日缺项为 **2017-01-01**；[上交所 2016-12-22 正式公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20161222_4218613.shtml)明确该日休市，已保存原文核销，不补交易日；无未解释历史缺口。[2025-12-22 公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)明确 2026-10-08 恢复开市，与日历一致。新增辅助取数仅为这两份官方休市公告，不改行情路由。
- 基础 Python 缺 pandas，首次 calendar 在写库前失败；在 `outputs/s1-venv` 按现有 requirements 安装依赖后导入成功。未改业务代码、参数或共享环境。写前 SQLite 备份在 `outputs/data/market-before-s1-calendar-2026-10-04.sqlite`。
- `git fetch origin --prune` 后指定远端分支相对 origin/main 未合并提交数为 0，已删除 `claude/bold-archimedes-8mka2j`；无同名本地分支。原 main 工作保留。

## 来源锚点与交付边界

本提交只纳入行情库与本页。`outputs/s1-preflight/` 的包仅为预检，**不是最终来源锚点**。推送后在最终 commit 运行 `python -m src.data package --end 2026-09-30` 及 `verify`，最终 `git_commit / content_sha256 / source_db_matches_commit=true` 记录于 `outputs/research-package-2026-09-30.MANIFEST.json` 并在交付回复中报告；包及依赖不入 Git。

S1 交付不等于研究放行：H00300 与其余失败/字段缺口交编排方处理。正式规则保持关闭；未运行 build、characterize/design/oos/rolling，未启用 cron。四项数据陷阱仍适用：主题回填偏差；指数≠ETF（研究结论每年 1% 折扣）；腾讯减法 qfq 不直接算收益（本库执行价 raw）；价格/全收益不可混用。未计算收益或研究结论。
