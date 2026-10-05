# H00300 服务器离线恢复

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 日期约束升级与原年度响应恢复
- Timestamp (UTC): 2026-10-04
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮授权；docs/h00300-offline-restore.md；main c7091f0

## 结果

| 校验 | 结果 |
|---|---|
| 代码与测试 | main 包含 c7091f0；SQLite 3.42.0；316 tests / OK（临时合成数据测试，非正式研究） |
| 升级 | 副本及正式库均仅新增六个日期触发器与 meta.date_constraints=gregorian-v1；存量非法日期 0 |
| 恢复来源 | run 1，28 响应校验通过，27 年度窗口入选，候选短窗 seq=0 排除 |
| 行情恢复 | H00300/raw 5,302 行，2005-01-01 至 2026-09-30；4,955 行缺 OHL，NULL close 0；source=csi，fetched_at 保留原请求时刻 |
| 历史保全 | 升级各表历史零差异；恢复仅新增 H00300 行、一条 backfill run 4、一条 T01 coverage，runs 计数器增一；其他行情、全部 exec_*、日历、请求、历史 runs/coverage、universe 均不变 |
| 幂等与完整性 | 两阶段 dry-run 不写；重复 apply 均 changed=false / idempotent=true，文件哈希不变；各库 integrity_check=ok，无热日志 |
| 质量阻断 | 默认窗口 2005-01-04 至 2026-09-30；preflight 正常返回 1，benchmark_ready=false / research_ready=false，副本与正式报告完全一致 |

原始 23 个非日历日期全部保留；默认窗口仅报告 22 个，2005-01-01 在窗口外。基准仍缺 2008-12-31、2009-12-31、2010-12-31；窗口内真实交易日缺 OHL 4,934 行。本轮不填值、不移动日期、不缩短窗口、不删容器。

## 执行证据与边界

验证目录 `outputs/h00300-validation-c7091f0/` 保存测试日志、升级与恢复 dry/apply/repeat、逐表双向 EXCEPT 与 schema/exec 字段保全报告、quality.json 及正式库对应报告。恢复副本严格来自已升级副本。只读 reviewer 结论 approve；主会话复核后才写正式库。

写前备份 `formal-before.sqlite` 为 SQLite backup，表/schema 全部一致但页面布局与原文件不同；错误的字节等同性断言触发暂停，正式库当时未写。逐表核对排除数据差异后另存 `formal-before-exact.sqlite` 字节精确备份（原 SHA256 `7eabb924646af87e615602416735bd971543e28747e1c94dd33d052f5db675e5`），再执行升级。升级后恢复前基线另存 `formal-upgraded-before-restore.sqlite`。

此前跨年短窗官方响应真实返回 H00300：2008-12-31 close=1883.37、2009-12-31=3739.99、2010-12-31=3306.94，均缺开高低；证据在 `outputs/data/h00300-cross-year-20261004T131217Z/`，**本轮未用于补库**。

仅提交 market.sqlite 与本页。数据提交推送后重新 package/verify，正式来源 commit、source_db_matches_commit 和 content_sha256 以新 MANIFEST 及交付回复为准；outputs 不入 Git。不运行正式 build/研究，不启用规则或 cron。日期约束修复与恢复成功不等于研究放行；已有数据陷阱与质量缺口继续适用。
