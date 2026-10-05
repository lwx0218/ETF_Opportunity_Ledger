# H00300 三个年末缺日独立离线补录

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 三个年末缺日补录代码、审计与年度恢复兼容
- Timestamp (UTC): 2026-10-05T11:36:55Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮指令；AGENTS.md；`operations/work_logs/2026-10-04-h00300-server-restore.md`

## 交付范围

从 `origin/main=81e101e999812c5d5b7cb7bd771cb7e424338357` 创建 `codex/h00300-year-end-supplement`。仅交付代码、合成测试及 Pi 说明，不执行真实补录、不运行研究。

- `offline-supplement` 默认只读；显式 `--apply` 才补 `2008-12-31`、`2009-12-31`、`2010-12-31`。校验官方 CSI 来源、唯一短窗、原响应字节数与 SHA256、合法日期、带时区获取时间；目标 close 正有限，OHL 保持 NULL。邻近行情只留作证据，不入库；已有目标行必须全部字段一致，冲突停止。
- 同一事务追加 backfill run、三个 requests、缺失目标 bars 和 T01 研究 coverage；run 内保存完整清单及完整 UTF-8 原响应、清单哈希、新增与原已一致日期。保留原历史与全部执行字段；写入前要求已升级 Gregorian 约束；中途失败全部回滚；重复执行字节幂等。
- 年度恢复严格保留原 27 年度响应与排除候选短窗的合同。额外三日只有经成功补录审计重新校验、重新解析且逐字段匹配现存 bars 后才能保留；标记或日期白名单不足以放行。总 coverage 不退回年度行数；年度恢复只插年度响应行，不替补录命令重插后来缺失的三日。
- Pi 原始目录在本机不存在，未能核验其采集清单格式。本包定义明确的 `h00300-year-end-v1` JSON 清单，由 Pi 从原采集记录离线整理，保留转换核对证据；不得从日志价格、文件 mtime 或新生成哈希补造来源。

## 测试与门禁

新增 28 项合成测试；目标 close 使用独立合成的 200/201/202，未硬编码服务器三个真实值。覆盖来源/查询参数/短窗/日期/哈希/路径/时间/OHL/close/量额错误、内嵌原文审计、只补三日、历史保全、默认只读、幂等、旧库约束门禁、请求/行情/coverage 写入故障回滚，以及年度前后兼容、审计篡改、无证据额外行拒绝、丢失补录行不由年度补回。网络入口打桩禁止。

| 验证 | 结果 |
|---|---|
| 定向补录 + 年度测试，SQLite 3.53.1 | 60 项 / 1.327 秒 / OK |
| 定向补录 + 年度测试，SQLite 3.42.0 | 60 项 / 1.380 秒 / OK |
| 完整测试，SQLite 3.53.1 | **344 项 / 53.848 秒 / OK** |
| 完整测试，SQLite 3.42.0 | **344 项 / 55.765 秒 / OK** |
| 独立只读 correctness review | **approve**；修复非法时区偏移分钟被 Python 归一化的问题，并独立验证 `±00:99` 拒绝且库哈希不变 |
| 官方 Ponytail 4.10.3 | **Lean already. Ship.**；独立 Codex 宿主按 `skills/ponytail-review/SKILL.md` 实际只读审查源码、最终 28 项测试和文档 |
| Git / 基线 | `git diff --check` 通过；重新 fetch 最新 main 仍为 `81e101e`，为本分支祖先，无冲突 |

以上测试均退出 0，无跳过、无失败。Python 为 3.12.14；精确 SQLite 3.42.0 沿用上轮核验的官方源码与隔离 pysqlite3 绑定，不改变开发环境默认 SQLite。命令与日志：

```bash
.venv/bin/python -m unittest discover -s tests -t .
/workspace/scratch/sqlite-3.42.0/python -m unittest discover -s tests -t .
# outputs/h00300-year-end-delivery/full-native.log
# outputs/h00300-year-end-delivery/full-sqlite342.log
```

## Pi 交接与边界

完整清单合同、副本 dry-run/apply/repeat、年度兼容复验命令见 `docs/h00300-year-end-supplement.md`。真实原件、完整清单及正式库补录由 Pi 按各自授权验证执行；本轮真实验证仍待 Pi，不能用合成通过代替。

正式 `data/market.sqlite` SHA256 始终为 `022af1e058cf6c368836291dde77583f57ee11b5ff5057dbb65511357ed532fb`，没有本轮数据写入。未抓行情、未执行真实 build 或研究、未启动规则/cron、未改治理文件。三个收盘补录并不填补策略所需 OHL，质量门禁不变。
