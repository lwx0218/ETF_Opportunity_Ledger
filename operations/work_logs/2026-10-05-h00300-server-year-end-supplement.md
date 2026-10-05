# H00300 三日服务器补录

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 原采集短窗证据定向补录三个年末收盘
- Timestamp (UTC): 2026-10-05T12:55:17Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮授权；docs/h00300-year-end-supplement.md；main b0b43e6

## 结果

| 校验 | 结果 |
|---|---|
| 测试 | main 包含 b0b43e6；344 tests / OK（临时合成测试，非正式研究） |
| 原证据 | 三条清单完全复制原 requests.json 字段，原字节/哈希与时间全匹配；不补造元数据 |
| 三日实际值 | 2008-12-31=1883.37；2009-12-31=3739.99；2010-12-31=3306.94；均 H00300/csi，OHL=NULL，量额与原获取时刻保留 |
| 行数 | 仅新增3行；H00300/raw总量5,305，缺OHL4,958；原23个非交易日不变 |
| 审计 | 新增backfill run 5、三个requests及一条T01 coverage；run内嵌清单与原响应可重新校验 |
| 保全 | 副本与正式库均逐表双向核对，全部旧行情/作业/请求/coverage、exec_*、日历、universe、meta与schema不变；仅上述新增及runs计数器+1 |
| 幂等 | dry-run不写；重复补录、年度恢复重验均changed=false/idempotent=true，文件SHA256不变；年度重验5302原行+3审计补录行，不退回coverage |
| 完整性与质量 | integrity_check=ok、foreign_key_check空、DELETE模式且无热日志；preflight返回1，benchmark_ready=true / research_ready=false，副本与正式报告完全一致 |

## 证据与边界

原件及采集清单保留在 `outputs/data/h00300-cross-year-20261004T131217Z/`。整理清单与来源核对记录在 `outputs/h00300-year-end-validation-b0b43e6/manifest.json`、`manifest-provenance.json`，清单SHA256为 `b14ada7b50f5fe7d39772c5f73e4160548a433d21d2472f8965045df06bf9040`。同目录保留tests、dry/apply/repeat/annual-repeat、逐表保全、quality及正式执行JSON；`formal-before.sqlite`为写前字节精确备份。副本只读review结论approve，主会话复核后才写正式库。

仅将 market.sqlite 与本页提交；数据提交推送后重新package/verify，最终来源commit、source_db_matches_commit=true与content_sha256在正式MANIFEST及交付回复中报告，outputs不入Git。

基准收盘就绪不等于研究就绪：OHLC和其他研究池缺口保持，不填值、不换指数、不缩窗口、不删池；未运行正式build/研究、未启用规则或cron。上轮 `operations/work_logs/2026-10-05-data-blocker-inventory.md` 与详细证据继续保留，未纳入本数据提交；其H00300三日收盘缺口结论以本次补录后的质量报告为更新，OHLC及其他容器阻塞仍有效。
