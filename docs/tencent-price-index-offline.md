# 腾讯价格指数候选离线导入

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: guide
- Status: active（代码与合成验证；真实原件复验待 Pi）
- Owner: Faye
- Last updated: 2026-10-06
- Source of truth: Owner 本轮指令；357d2f3；operations/work_logs/2026-10-06-tencent-price-candidates.md 及同名 index.json

## 固定批次与边界

`python -m src.data offline-tencent-price` 仅导入已批准的 `000852`（中证1000）与 `000905`（中证500），2005–2025 完整年度及 2026-01-01 至 09-30，共 44 个原响应。索引固定为提交 357d2f3 的文件，SHA256 为 `f2865c4884cc9d5c290c03f17afc75c2a74550376d31a2f9cbb1174c30a8603b`；没有替换索引、增加代码、缩短年度或忽略失败的选项。缺原件即停止，无网络请求或回退。

重验每份原文的字节数与 SHA256、HTTP/业务状态、唯一 URL/参数、带时区获取时刻、`qt[symbol][:3]` 代码和中文名称，以及 `day` 数组。顺序是 `date,open,close,high,low,原始量`，不回退 `qfqday`。日期须为真实且严格递增的 `YYYY-MM-DD`，每年窗口内集合须与目标库官方 calendar 完全一致，并重算索引的计数、首尾和裁剪统计。原响应窗外行仍校验日历、日期、获取时刻与 OHLC；只在验证后裁掉，不导入。跨响应同日 OHLC 必须一致，不以去重吞掉重复或冲突。

所有 OHLC 必须正、有限，满足 `low ≤ open/close ≤ high`，不补空值。原始量单位尚未核实，`volume/amount` 一律 NULL；完整原量留在原文审计中。qfq 请求参数不使这些指数成为全收益或 ETF 后复权，不将它们与 H00852/H00905 拼接。

导入写入 `bars(code=000852/000905, adj=raw, source=tencent_price_index_offline)`，与旧 `tencent_index` 网络路由区别登记。沿用 `market-v1`，没有新增 schema：`runs.kind=backfill`，`args.offline_tencent_price_import=true`，顶层及逐序列登记均为 `price_only=true`；原文索引、44 个完整响应、官方日历窗口哈希、插入/原有日期分区、证据提交和执行代码 SHA 随作业保存，`requests` 保存原 URL/文件名/哈希/字节数/获取时刻。每行 fetched_at 来自其所属年度响应，重叠年不会改写它。

不改变 coverage、coverage_latest、universe、任何已有全收益/执行行情、日历或历史审计，不改变研究纳入。价格/全收益区别、指数与 ETF 每年 1% 的研究折扣、回填历史、腾讯减法 qfq 的陷阱仍按 intake §4.2 处理；本导入不计算收益、指标或研究结果，也不授权启用规则/cron。

## 事务、冲突与幂等

默认 SQLite `mode=ro` 和 `query_only`，只读 dry-run 不建库或升级。`--apply` 对现存库使用 `BEGIN IMMEDIATE`，所有校验通过后在同一事务追加 runs、requests 和缺失行情；任意失败全部回滚。旧库必须先显式完成已有日期约束升级，导入不偷偷迁移。

已有目标 raw 行必须逐字段完全一致，包括 NULL、来源和获取时刻；目标代码的证据外 raw 行、其他来源或任何差异均停止，不覆盖，也没有 force。首次已有少量完全一致行可保留并补缺，审计记录保留日期。已有成功审计则必须与原证据及行情完整一致；请求指纹会定位标记丢失或作业类型被改动的旧审计，损坏停止报告，不再追加一份审计掩盖。重复成功执行不增作业/请求，不改变文件字节。

## Pi：先副本复验

以下命令在仓库根目录执行。保留原响应于 `outputs/data/tencent-price-candidates-20261006/recorded/`，先升级代码；本云工作区没有这 44 份原件，不能宣称真实导入已通过。首次干净导入预期两个代码各 5,282 行、合计 10,564，原始 13,924、裁掉 3,360。已有完全一致目标行时只插入缺行。

先用 SQLite backup 复制一致快照；已有验证目录不覆盖。`before.sqlite` 是保全基线，`copy.sqlite` 是唯一写入目标。

```bash
.venv/bin/python - <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
from src.data.db import sha256_file

folder = Path('outputs/tencent-price-import-validation')
folder.mkdir(parents=True, exist_ok=False)
formal = Path('data/market.sqlite').resolve()
(folder / 'formal.sha256').write_text(sha256_file(formal) + '\n')
with closing(sqlite3.connect(formal.as_uri() + '?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(folder / 'before.sqlite')) as before:
        source.backup(before)
with closing(sqlite3.connect((folder / 'before.sqlite').resolve().as_uri() + '?mode=ro', uri=True)) as before:
    with closing(sqlite3.connect(folder / 'copy.sqlite')) as target:
        before.backup(target)
PY

# 如日期约束尚未升级，先审计副本，再显式升级；非法存量日期应停止。
.venv/bin/python -m src.data upgrade-date-constraints --db outputs/tencent-price-import-validation/copy.sqlite
# 仅确需升级时执行：
# .venv/bin/python -m src.data upgrade-date-constraints --db outputs/tencent-price-import-validation/copy.sqlite --apply
# 旧库升级会改变 meta/触发器：升级完成后应重新建立验证基线，区分升级与本次导入。

.venv/bin/python -m src.data offline-tencent-price --db outputs/tencent-price-import-validation/copy.sqlite --recorded-dir outputs/data/tencent-price-candidates-20261006/recorded
.venv/bin/python -m src.data offline-tencent-price --db outputs/tencent-price-import-validation/copy.sqlite --recorded-dir outputs/data/tencent-price-candidates-20261006/recorded --apply
sha256sum outputs/tencent-price-import-validation/copy.sqlite > outputs/tencent-price-import-validation/once.sha256
.venv/bin/python -m src.data offline-tencent-price --db outputs/tencent-price-import-validation/copy.sqlite --recorded-dir outputs/data/tencent-price-candidates-20261006/recorded --apply
sha256sum --check outputs/tencent-price-import-validation/once.sha256
```

第二次应报告 `idempotent=true`、`changed=false`、`rows_to_insert=0`。保全检查使用两个只读库，逐表双向比较，审计表只允许追加：

```bash
.venv/bin/python - <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
from src.data.db import sha256_file

folder = Path('outputs/tencent-price-import-validation')
assert sha256_file(Path('data/market.sqlite')) == (folder / 'formal.sha256').read_text().strip()
with closing(sqlite3.connect((folder / 'copy.sqlite').resolve().as_uri() + '?mode=ro', uri=True)) as con:
    con.execute('ATTACH DATABASE ? AS baseline', ((folder / 'before.sqlite').resolve().as_uri() + '?mode=ro',))
    con.execute('PRAGMA query_only=ON')
    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    maximum = con.execute('SELECT coalesce(max(run_id),0) FROM baseline.runs').fetchone()[0]
    for table in ('meta', 'calendar', 'coverage', 'universe', 'update_results', 'bars', 'runs', 'requests'):
        where = (" WHERE NOT(code IN ('000852','000905') AND adj='raw')" if table == 'bars'
                 else f' WHERE run_id <= {maximum}' if table in ('runs','requests') else '')
        for left, right in (('main', 'baseline'), ('baseline', 'main')):
            assert not con.execute(f'SELECT * FROM {left}.{table}{where} EXCEPT SELECT * FROM {right}.{table}{where}').fetchall(), table
    for code in ('000852', '000905'):
        result = con.execute("SELECT count(*),min(date),max(date),sum(source<>'tencent_price_index_offline' OR volume IS NOT NULL OR amount IS NOT NULL) FROM bars WHERE code=? AND adj='raw'", (code,)).fetchone()
        assert result == (5282, '2005-01-04', '2026-09-30', 0), (code, result)
print('副本完整性、其它历史保全、正式库未改：通过')
PY
```

## Pi：副本通过后正式入库

保留上述副本与日志。确认正式库期间未被其他作业改写，再做正式库 dry-run；输出与副本一致后显式 apply。下面是交付给 Pi 的操作命令，本开发任务未执行正式 apply。

```bash
.venv/bin/python -m src.data offline-tencent-price --db data/market.sqlite --recorded-dir outputs/data/tencent-price-candidates-20261006/recorded
.venv/bin/python -m src.data offline-tencent-price --db data/market.sqlite --recorded-dir outputs/data/tencent-price-candidates-20261006/recorded --apply
sha256sum data/market.sqlite > outputs/tencent-price-import-validation/formal-once.sha256
.venv/bin/python -m src.data offline-tencent-price --db data/market.sqlite --recorded-dir outputs/data/tencent-price-candidates-20261006/recorded --apply
sha256sum --check outputs/tencent-price-import-validation/formal-once.sha256
```

沿用上方只读比较块，把连接目标改为 `data/market.sqlite` 并去掉“正式库未改”的哈希断言，继续对 `before.sqlite` 验证其它历史保全。如有旧日期约束，正式升级须独立审计并显式执行；不要将升级产生的元数据变化误算为导入。提交数据检查点前按仓库要求核对 `integrity_check` 和无热日志；不运行正式研究。

## 开发复验

```bash
.venv/bin/python -m unittest tests.data.test_tencent_offline
.venv/bin/python -m unittest discover -s tests -t .
```

合成测试覆盖 44 个完整年度窗口、闰日、窗外重叠、缺日/非交易日/OHLC/身份/哈希/时刻拒绝、路径逃逸、完整审计及损坏识别、其它历史逐表保全、两序列中途失败回滚、文件级幂等与旧库升级边界。测试不把合成工作日日历当作真实日历验证结论；真实 Pi 复验必须使用目标库已有官方 calendar。
