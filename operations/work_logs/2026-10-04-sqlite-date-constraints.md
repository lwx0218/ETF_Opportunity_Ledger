# SQLite 日期约束修复与显式升级

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: SQLite 3.42.0 日期约束回归及旧 market-v1 升级
- Timestamp (UTC): 2026-10-04T15:40:56Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮指令；AGENTS.md；`docs/data-layer.md`

## 范围与实现

从最新 `origin/main=ab64650b0cbc009030e2ef8a9b1bbaceffabe9e8` 创建 `codex/sqlite-date-constraints`。

- `bars.date`、`calendar.date`、`runs.end_date` 使用固定格式、公历月长、4/100/400 年闰年规则，域为 `0001–9999`；不依赖 SQLite 对不存在日期的 `date()` 归一化。新表 CHECK、持久化 INSERT/UPDATE 触发器和旧库审计共用规则。
- `runs.end_date=NULL` 与行情 OHLC NULL 保留；合法周末/休市日行情保留；calendar 原有周末禁令不变。
- 新增 `upgrade-date-constraints --db ...`，默认只读 dry-run；显式 `--apply` 才以单个事务追加六个触发器和 `meta.date_constraints=gregorian-v1`。不重建表，不变更原表 DDL、root page、数据和 `sqlite_sequence`，不追加 runs。存量非法日期报告全部位置与值后停止；DDL/标记写入失败全部回滚；重复 apply 不写文件。
- 普通写入口及 offline-restore apply 在约束缺失时拒绝，要求先显式升级；readonly、preflight、package 源库及恢复 dry-run 不迁移。未知修订及同名触发器冲突停止，不自动覆盖。

## 验证

原 `ab64650` 快照：SQLite 3.42.0 的 `tests.data.test_runner.Schema` 执行 4 项，准确复现 `test_runner.py:509` 一项失败（`2026-02-30` 未拒绝）；SQLite 3.53.1 同样 4 项通过。

精确 3.42.0 环境使用官方 SQLite GitHub tag `version-3.42.0`（commit `89efa897780db03eac974eb6b0e041cfb7c39733`）与隔离编译的 pysqlite3 0.5.1 绑定。PyPI 源包 SHA256 核验为 `45496b7a5e5931afb9993f76ce48873d126abfc0fe70b65373970d353fca2c24`；TLS 正常验证。SQLite source ID 为 `2023-05-16 12:36:15 831d0fb2836b71c9bc51067c49fee4b8f18047814f2ff22d817d25195cf350b0`。仅测试启动脚本启用该绑定并断言版本，主 `.venv` 保持 Python 3.12.14 / SQLite 3.53.1；未改依赖声明。

```bash
.venv/bin/python -m unittest discover -s tests -t .
/workspace/scratch/sqlite-3.42.0/python -m unittest discover -s tests -t .
```

新增 14 个回归测试。冻结旧 schema fixture 已与 `ab64650` 精确核对；覆盖直接 SQL 的 INSERT/UPDATE/REPLACE/UPSERT、闰年与边界、NUL/BLOB、NULL/周末、只读保全、原历史数据及原 DDL 保全、幂等、失败回滚，以及 offline-restore 的旧库拒绝、升级后恢复和约束不完整拒绝。相关 44 项已在两个 SQLite 版本通过，无跳过。

完整测试：SQLite 3.53.1 为 **316 项 / 102.448 秒 / OK**；SQLite 3.42.0 为 **316 项 / 106.607 秒 / OK**。两个命令均退出 0，没有跳过或失败测试。运行日志保存在 `outputs/sqlite-date-constraints/`；版本来源及原失败证据位于 `/workspace/scratch/sqlite-3.42.0/`，均不入 Git。

独立只读 reviewer 结论 **approve**，无阻塞 findings；独立运行 3.42.0 的相关 16 项测试通过。另在两个 SQLite 版本上分别对 1800–2199 年、month=0..13、day=0..32 的三个字段做各 **554,400 次** SQL 与 Python 公历/工作日规则对照，均 0 mismatch。

独立 Ponytail reviewer 在 Codex 宿主按官方 Ponytail 4.10.3 的 `skills/ponytail-review/SKILL.md` 执行准入审查，覆盖实现、文档及最终测试；结论 **Lean already. Ship.**，无复杂度 findings。`git diff --check` 通过；交付前重新 fetch 的 `origin/main` 仍为 `ab64650`，是本分支祖先，无合并冲突。

## 边界与 Pi 交接

未改正式行情库；`data/market.sqlite` SHA256 保持 `7eabb924646af87e615602416735bd971543e28747e1c94dd33d052f5db675e5`。未补三个收盘价、未运行真实研究、未抓行情、未开规则或 cron，未改治理文件。全套测试仅使用合成临时数据。

Pi 在副本上的升级及离线复验命令见 `docs/h00300-offline-restore.md` 的「SQLite 日期约束升级」。正式库应用及恢复写入仍按各自授权，不包含在本轮代码合并授权内。
