# H00300 离线恢复与研究输入校验

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: H00300 离线恢复与正式 build 输入质量门禁
- Timestamp (UTC): 2026-10-04T12:53:14Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 2026-10-04 本包指令；AGENTS.md；`operations/work_logs/2026-10-04-s1-data-delivery.md`

## Goal / Summary

从最新 `origin/main` 的 `df812b7b2fb6613fad624aa407f5f209d3782641` 建立独立分支 `codex/h00300-offline-restore`。Owner 已授权本包实现、任务分支推送与草稿 PR；不直接推 main 或合并。

## Scope / Changes

- `offline-restore` 默认 dry-run，按指定 requests 作业逐个核验原文件，复用 CSI 纯解析器，仅恢复年度窗口。显式 `--apply` 在一个事务内补 H00300/raw、追加 T01 研究 coverage 和带 `offline_restore` 标记的 backfill 作业。
- 保留原日期、NULL、来源和逐请求获取时刻；短窗不拼入，冲突不覆盖。执行行情、执行 coverage、日历和既有历史不改。精确重复执行不产生新写入。
- `preflight` 始终只读，分别输出 `benchmark_ready` / `research_ready`；按官方日历过滤计算视图，缺交易日收盘或策略真实 OHLC 即阻断，不自动剔除容器。正式 build 在指标计算/输出之前调用同一预检。
- 保持海外 D−1 及 I-24 原生预热；预热数据同样要求真实 OHLC。每日 live 路径未在本包扩展，不做 P6g。
- 使用独立 builder、测试代理、只读 reviewer 与官方 Ponytail 技能复核。仅修改业务源码、测试、数据/指标文档及本次工作日志；治理文件、规则配置、正式数据库均未改。

## Validation

- `.venv/bin/python -m unittest discover -s tests -t .`：**292 tests，59.857s，OK**。套件中的研究引擎用例仅运行合成临时输入，不是实际研究或冻结样本外运行。
- 覆盖：默认 dry-run/显式 apply、缺文件/缺年/哈希不符、短窗排除、非法日期/重复日期/冲突源/获取时刻、NULL 保留、事务中途失败回滚、字节级幂等、执行与历史字段不变；基准与策略分离、三缺日/首尾缺日、官方日历边界、禁止自动剔除、OHLC 无效值、非交易日只过滤视图、失败 build 保留已有输出、海外预热对拍。
- `git diff --check` 通过；`git diff --exit-code df812b7 -- data/market.sqlite config/ledger-rules.json AGENTS.md .pi` 通过。
- 本次只读查看 S1 作业/请求元数据：28 个成功 H00300 响应属于 probe run 1，短窗 seq 0、年度 seq 1–27；run 2 backfill 的 H00300 请求为 403。原录件目录在本机不存在，未执行真实恢复。
- 对未恢复 S1 库运行只读质量预检：37 个已声明研究容器、H00300 0 行，`benchmark_ready=false`、`research_ready=false`；官方日历 5,343 日，2005-01-04 至 2026-12-31。前后文件 SHA-256 均为 `7eabb924646af87e615602416735bd971543e28747e1c94dd33d052f5db675e5`。仅查看结构/缺项诊断，不计算收益或研究结论；报告留在忽略目录 `outputs/h00300-validation/baseline-quality.json`。

## Review / Gate

- 独立只读 reviewer：**approve**，无剩余实质问题。首次复核指出 strict build 剪掉海外 2005 年前预热，已修复；独立合成对拍与两个回归用例确认保留预热，缺 OHLC 时阻断。
- Ponytail：从 npm 官方 `@dietrichgebert/ponytail@4.10.3` 获取并验证 `dist.integrity`，由 Codex 宿主执行该包 `skills/ponytail-review/SKILL.md`。此为 Pi `/ponytail-review` 使用的同一技能，专审复杂度；没有独立 CLI，也未冒称运行 Pi extension。删除两个未用 import 后最终结论 **Lean already. Ship.** 正确性由上一项独立复核负责。

## Decision / Next Steps

真实 28 原文件校验、5,302 行恢复、23 个非交易日、4,955 行缺开高低及三缺日复验，均待 pi 按 `docs/h00300-offline-restore.md` 在服务器验证副本上执行。上述真实计数来自 Owner 已核验背景，本次不冒充复验。正式数据库写入、行情修复、实际研究、规则和 cron 都不在本包执行范围。

GitHub API 只读探测被环境出网代理拒绝：`CONNECT tunnel failed, response 403`（`api.github.com`）；不将此误报为 Git HTTPS 推送权限不足。远端提交/PR结果以本次最终交付为准。
