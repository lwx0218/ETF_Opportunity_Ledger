# H00300 三个年末缺日离线补录

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: guide
- Status: active（代码及合成验证；真实录件复验、补录待 Pi）
- Owner: Faye
- Last updated: 2026-10-05
- Source of truth: Owner 本轮指令；`operations/work_logs/2026-10-04-h00300-server-restore.md`；`docs/data-layer.md`

## 补录范围

`offline-supplement` 仅处理 `H00300/raw` 的 `2008-12-31`、`2009-12-31`、`2010-12-31`，三日证据必须同时完整。默认只读 dry-run，显式 `--apply` 才在单个事务中只补缺行。已有目标行须连同 NULL、来源、获取时刻逐字段一致，否则整个任务停止，不覆盖。合法非交易日历史、执行行情、执行 coverage、日历、schema、meta、universe、其他作业历史均保留。

服务器基线 `main=81e101e` 已完成日期约束升级及 5,302 行年度恢复。本命令要求已有 T01 的 H00300/raw/csi 全收益研究 coverage 及同源行情；写入前核验 Gregorian 约束，不顺带迁移。全年恢复仍按原年度响应执行，本命令没有网络路径，不替代其他日期修复，不运行研究。

## Pi 原始证据清单

服务器记录的证据目录是 `outputs/data/h00300-cross-year-20261004T131217Z/`。开发环境没有该目录及原始采集清单，不能宣称真实文件已经通过。Pi 需从**原采集记录**离线整理 UTF-8 JSON 清单：

```json
{
  "format": "h00300-year-end-v1",
  "requests": [
    {
      "url": "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=H00300&startDate=20081230&endDate=20090105",
      "file": "原2008年短窗响应文件名.body",
      "bytes": 1234,
      "sha256": "原采集记录中的64位SHA256",
      "fetched_at": "原采集记录中的带时区获取时间",
      "error": null
    }
  ]
}
```

上例仅说明单个请求字段，文件名、窗口及元数据均为示意，不能照抄；正式数组须包含三个请求，分别覆盖三个目标日。不能从工作日志的收盘摘要造响应，不能用文件 mtime 或本次运行时间替代 `fetched_at`，不能在文件不匹配时重算并覆盖原哈希。清单位置可自选；响应默认相对清单目录定位，`--recorded-dir` 可指定 Pi 原件目录。保留原采集清单、整理清单及两者的核对记录；缺少原来源/时间/哈希时停止。

验证规则：

- URL 必须唯一指向官方 CSI `index-perf` HTTPS 接口，且只有 H00300、起止日期三个查询参数。每个短窗起止日期差不超过 45 天，包含唯一目标年末日；不允许重复或缺少年度证据。
- 每个文件路径必须在录件目录内，禁止绝对路径、`..`、逃出目录的软链接。严格 UTF-8 解码，核对原字节数和 SHA256；有采集错误则拒绝。
- `fetched_at` 必须含 `T`、秒与时区（如 `2026-10-04T13:12:17Z`），不晚于本次执行时间，也不早于目标日北京时间 15:30 的既有行情可用边界；保存原字符串，不以本次执行时间替换。
- 响应须为成功 CSI 行情数组，每行明确 `indexCode=H00300`，日期合法、不重复且在请求窗口内。仅选指定目标行，邻近日期不入库；原文全部保留。
- 复用 CSI 解析器。目标真实收盘须为正有限数值；OHL 只能缺失、NULL 或原接口的空值标记，入库保持 NULL。有真实 OHL 时停止，不静默丢弃，更不以 close 填充。成交量/金额按原响应解析保留，不推算。

哈希证明文件与采集记录一致，不是官方数字签名。来源信任锚仍是 Pi 保存的官方采集原件和原采集元数据。

## 审计、幂等与年度恢复兼容

一次 apply 原子追加 `kind=backfill`、`args.offline_supplement=true` 的 run、三个 requests、缺少的目标 bars，以及一条更新后的 T01 coverage。run 记录清单 SHA256、完整清单文本、三个完整原响应文本、实际新增日期和原已一致日期。UTF-8 文本重新编码精确复原原字节，因此不需要新表或外部文件即可重验。原作业、原请求、原 coverage 不改；新 coverage 只更新研究统计及本次审计说明，全部执行字段保留。任一步失败回滚整个事务。同一清单、行情和 coverage 状态重复 apply 为字节幂等，不增加历史。

年度 `offline-restore` 仍严格核验原 28 响应，并排除原 45 天候选短窗。年度响应之外的已有行，只在属于这三个目标日且有完整成功补录审计时才接纳：重新核对内嵌清单与请求记录、原文的字节数/哈希/来源/日期/时间，再重新解析并逐字段比较 bars。单独日期白名单、run 标记或手工补行都不足以放行。其他额外日期、被改价格/NULL/获取时刻、缺失或不一致审计均拒绝。

年度 coverage 按年度原行与**已存在且已证实**的补录行合计；报告分别给出 `annual_rows`、`retained_supplement_dates`、`supplement_run_ids` 和总 `rows`。年度命令仍只插入年度响应行，不顺带重插后来缺失的补录行。正常顺序“年度恢复 → 补录 → 再跑年度恢复 → 再跑补录”保持幂等，coverage 不退回 5,302 行。

## Pi 在副本上执行

以下命令以已核对的整理清单为输入，仅对新建副本 apply。首次执行后保留整个目录；重复验证应换目录，不能覆盖已有结果。

```bash
set -e
PY=outputs/s1-venv/bin/python
VERIFY_DIR=outputs/h00300-year-end-validation
RECORDED=outputs/data/h00300-cross-year-20261004T131217Z
MANIFEST="$RECORDED/offline-supplement-manifest.json"
"$PY" -m unittest discover -s tests -t .
test ! -e "$VERIFY_DIR"
mkdir -p "$VERIFY_DIR"
"$PY" - <<'PY'
import sqlite3
from pathlib import Path
src = sqlite3.connect(Path('data/market.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
dst = sqlite3.connect('outputs/h00300-year-end-validation/market.sqlite')
src.backup(dst)
dst.close()
src.close()
PY
VERIFY_DB="$VERIFY_DIR/market.sqlite"
"$PY" -m src.data offline-supplement --db "$VERIFY_DB" --manifest "$MANIFEST" --recorded-dir "$RECORDED" > "$VERIFY_DIR/dry-run.json"
"$PY" -m src.data offline-supplement --db "$VERIFY_DB" --manifest "$MANIFEST" --recorded-dir "$RECORDED" --apply > "$VERIFY_DIR/apply.json"
sha256sum "$VERIFY_DB" > "$VERIFY_DIR/after-apply.sha256"
"$PY" -m src.data offline-supplement --db "$VERIFY_DB" --manifest "$MANIFEST" --recorded-dir "$RECORDED" --apply > "$VERIFY_DIR/repeat.json"
"$PY" -m src.data offline-restore --db "$VERIFY_DB" --source-run-id 1 --recorded-dir outputs/data/recorded --apply > "$VERIFY_DIR/annual-repeat.json"
sha256sum -c "$VERIFY_DIR/after-apply.sha256"
"$PY" -c 'import sqlite3,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; c.close()' "$VERIFY_DB"
```

Pi 核对首次只新增三行、总量预计 5,305、缺 OHL 预计 4,958；三个 close 以官方原响应为准，程序没有硬编码真实价格。核对 run/requests/coverage 的新审计以及全部原表历史逐值保全，所有 `exec_*` 原样保留；重复与年度重跑均应 `changed=false / idempotent=true`、文件哈希相同。测试已覆盖这些合同，真实计数仍待 Pi 原件复验。

补收盘不补 OHL、不解除研究门禁。需要时另行运行只读 preflight，不能把 `benchmark_ready` 等同于 `research_ready`；本包不运行 build 或研究。正式库补录由 Pi 按真实数据应用授权执行，代码合并不自动授权正式库写入。
