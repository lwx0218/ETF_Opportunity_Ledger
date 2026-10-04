# H00300 离线恢复与研究输入校验

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: guide
- Status: active
- Owner: Faye
- Last updated: 2026-10-04
- Source of truth: Owner 本包指令；`docs/data-layer.md`；`operations/work_logs/2026-10-04-s1-data-delivery.md`

## 范围

恢复 `requests` 已锚定的 CSI H00300 年度原响应。全程离线，既不重抓行情，也不计算研究收益。本命令不替换缺失年份、不用短窗补年度缺口、不补 OHLC、不启用规则。

`offline-restore` 默认 dry-run，只读打开库；只有 `--apply` 才写入。输入包括已有行情库、原响应目录、明确的来源作业 ID。本次 S1 的 28 个成功响应属于 **probe run 1**：27 个年度窗口（2000–2026，最后一年截至 2026-09-30）和 1 个 45 天候选短窗。backfill run 2 的 H00300 请求失败，不是恢复来源。

## 恢复合同

- 用来源作业的 `requests.file / bytes / sha256` 核验所有 H00300 原响应，短窗也要通过核验；路径不得逃出录件目录。年度窗口必须唯一且齐全，未知窗口、缺文件、`requests.error`、哈希不符或重复日期均拒绝，不联网回退。沿用 CSI 起点前无数据的处理：首条数据之前的空业务错误响应保留 warning，说明起点可能被截短；有行情之后的业务错误拒绝。
- 复用在线 CSI 行解析器的纯解析入口。日期和 NULL 原样保留；每行 `source=csi`，`fetched_at` 取该年度请求的原获取时刻。恢复包括非交易日原行，过滤只发生在后续计算视图。
- `H00300/raw` 的已有行只能是恢复结果的完全一致子集；数值、来源、获取时刻或额外日期冲突时拒绝覆盖。只补缺失行。
- 同一个事务内写 bars、追加 T01 coverage、追加 `kind=backfill` 且 `args.offline_restore=true` 的 runs 记录。保留原 schema；研究字段更新，T01 执行字段原值复制。原 coverage、requests、runs、其他序列、日历、universe 和 meta 不改。
- 新 run 记录来源作业、请求序号、证据摘要与原始哈希；失败回滚整个事务。相同证据及相同目标状态重复 apply 不新增行情、coverage 或作业。

## SQLite 日期约束升级

SQLite 3.42.0 会把部分不存在日期（例如 `2026-02-30`）原样通过旧 `date(value) IS value` 约束。新代码用明确的公历校验，同时提供旧 `market-v1` 的显式约束升级。`offline-restore --apply` 和普通数据写入口要求 `gregorian-v1` 修订及完整触发器；恢复入口不会顺带迁移。dry-run 仍可只读核验旧库的录件。

Pi 先在停写且无热日志的行情库副本上复验；以下命令不会写正式库，也不会运行研究。使用项目已安装依赖的 Python（例如 `outputs/s1-venv/bin/python`）：

```bash
set -e
PY=outputs/s1-venv/bin/python
VERIFY_DB=outputs/market-date-constraints-check.sqlite
test ! -e "$VERIFY_DB"
cp data/market.sqlite "$VERIFY_DB"
"$PY" -c 'import sqlite3; print(sqlite3.sqlite_version)'
"$PY" -m unittest discover -s tests -t .
"$PY" -m src.data upgrade-date-constraints --db "$VERIFY_DB"
"$PY" -m src.data upgrade-date-constraints --db "$VERIFY_DB" --apply
"$PY" -m src.data upgrade-date-constraints --db "$VERIFY_DB" --apply  # changed=false / idempotent=true
"$PY" -m src.data offline-restore --db "$VERIFY_DB" --source-run-id 1 --recorded-dir outputs/data/recorded
```

任何命令失败即停止。非法存量日期会列在 `invalid_dates`，连同总数 `invalid_count` 输出，退出 1；不得先改历史日期来强行升级。升级只改变触发器和 `meta.date_constraints`，不改 bars、calendar、coverage、requests、runs、universe 或其他历史行，不增加作业记录。`runs.end_date=NULL`、原始 OHLC NULL、合法非交易日行情保留。升级失败会回滚新增 DDL 和标记；再次 apply 为字节幂等。只读审计不写入、不建库，升级命令没有网络路径。

真实库应用和恢复写入仍需各自授权；本轮只交付代码和合成验证。三个缺失收盘价、研究放行与运行不在本轮范围内。升级本身不会改变质量预检结论。

## 只读预检与正式 build

```bash
python -m src.data preflight --db data/market.sqlite --end 2026-09-30
```

JSON 报告分别给出 `benchmark_ready`、`research_ready`，以及每个容器的缺收盘日期、缺 OHLC 日期、被计算视图排除的非交易日与原因。退出码 0 表示 `research_ready=true`；质量阻断返回 1，JSON 仍是有效报告。

请求窗口与可信覆盖范围分别声明，预检与正式 build 共用窗口及原行情选择函数：

- `preflight --start D --end D` 与 `build --start D --package ...` 使用同一窗口；build 的终点取包的 `end`。省略 `--start` 时取官方 `calendar` 的首个交易日，保留日历覆盖的全部历史，没有固定年份截断。
- 可信日历范围是 `calendar` 已验证日期的首日至末日。显式起点早于首日或终点晚于末日均阻断；包括元旦，不再假设首日前 14 天全部休市。窗口内部的周末/休市日仍由官方日历排除。官方覆盖范围外的原行情日期单列 `outside_trusted_calendar_dates`，无法判定是否交易日，不把它们冒充休市。
- JSON 的 `requested_window` 保存用户声明（默认起点为 null），`trusted_calendar_range` 保存可信覆盖范围，`effective_window` 保存解析后的起止和首末实际交易日。三项同时保存在成功 build 报告的 `input_quality` 与面板 `meta` 中，可据此核对预检与产物的范围。显式缩小窗口是调用方声明，不代表补齐窗口外历史；日历真实性仍以上游证据为准。

- 基准：官方窗口每个交易日都必须有正、有限的 H00300 原始收盘。开高低缺失可单独报告，不影响 `benchmark_ready`。首尾缺日也阻断，不按行情实际终点缩短检查。
- 研究：对 universe 与 coverage 声明的全部 retained/flagged 容器检查，缺 coverage 或序列不自动跳过。A 股序列从其登记起点起检查至窗口末尾；缺交易日真实收盘阻断。策略必须有正、有限的原始 OHLC，不得把收盘补成开高低后放行。T01 既是基准来源又是研究容器，因此可以基准就绪而研究未就绪。
- 海外序列只检查实际会被 D−1 消费的原生 OHLC：日期严格早于窗口的最后一个实际 A 股交易日，包含窗口前用于 I-24 指标预热的已有历史（`native_warmup_rows`）。末个 A 股交易日及之后的原生行情列在 `unavailable_native_dates`，不会证明本窗口可用，也不因这些尚未消费的行缺 OHLC 而误阻断。`alignable_rows` 为按 D−1 能产出的窗口行数，为 0 时阻断。仍沿用现有休市/断档规则，不要求每个 A 股交易日都有一根海外原始 K 线；窗口前已有行情仍按旧平盘及 `data_hole` 规则处理。成交量缺失仍按已有 I-21 报告。
- `python -m src.indicators build --package ...` 在包哈希复验后、指标计算和任何面板写入前执行同一预检。阻断时打印完整质量报告并失败，已有面板不改；通过后计算视图按官方日历过滤国内非交易日，基准读取真实收盘，原始包与库保持不变。成功报告包含 `input_quality`。

本包只接正式研究 build；每日任务 live 路径的后续改造属于另包，不借本任务推进 P6g。

容器可得起点以 coverage 与原始行情中较早的日期为准；这不是对指数上市史或回填历史完整性的外部证明。基准始终按完整官方窗口检查，不因 coverage 缩短而放行。

例如可信日历从 2004-11-01 开始时，默认预检与 build 都保留 2004 年有效数据；可信日历从 2005-01-04 开始时，显式 `--start 2004-11-01` 会阻断并要求补充可信日历，不能靠丢掉 2004 年静默放行。单独诊断与随后构建应使用相同的 `--start` 声明。

## pi 执行说明

开发环境没有服务器原响应，以下真实恢复必须由 pi 在服务器离线执行。先完整执行上面的「SQLite 日期约束升级」，确认升级保全及重复 apply 幂等通过。以下从已升级的 `outputs/market-date-constraints-check.sqlite` 再备份恢复副本，保留升级后的恢复前基线；不能重新从尚未升级的正式库复制后直接恢复。先进入项目并激活服务器已有的 Python 环境，勿直接对真实库 apply：

```bash
source outputs/s1-venv/bin/activate
python -m unittest discover -s tests -t .
mkdir -p outputs/h00300-validation
python - <<'PY'
import sqlite3
from pathlib import Path
p = Path('outputs/h00300-validation/market.sqlite')
if p.exists():
    raise SystemExit('验证副本已存在；保留旧结果，请改用新的目录')
src = sqlite3.connect(Path('outputs/market-date-constraints-check.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
dst = sqlite3.connect(p)
src.backup(dst)
dst.close()
src.close()
PY

# 默认 dry-run：成功只证明恢复证据完整，不代表研究就绪。
python -m src.data offline-restore \
  --db outputs/h00300-validation/market.sqlite \
  --source-run-id 1 --recorded-dir outputs/data/recorded \
  > outputs/h00300-validation/dry-run.json

# 仅对验证副本 apply，然后重复一次验证幂等。
python -m src.data offline-restore \
  --db outputs/h00300-validation/market.sqlite \
  --source-run-id 1 --recorded-dir outputs/data/recorded --apply \
  > outputs/h00300-validation/apply.json
python -m src.data offline-restore \
  --db outputs/h00300-validation/market.sqlite \
  --source-run-id 1 --recorded-dir outputs/data/recorded --apply \
  > outputs/h00300-validation/repeat.json

# 当前已知数据应返回 1：这是阻断生效，不可绕过。
python -m src.data preflight \
  --db outputs/h00300-validation/market.sqlite --end 2026-09-30 \
  > outputs/h00300-validation/quality.json
```

pi 核对：28 个响应校验通过、27 个年度响应入选、短窗序号 0 被排除、恢复 **5,302 行**、其中 **4,955 行缺开高低**；原 23 个非交易日仍在原始 bars，但被计算视图排除；缺 **2008-12-31、2009-12-31、2010-12-31** 的基准收盘，因此 `benchmark_ready=false`，策略 OHLC 和其他容器问题也使 `research_ready=false`。这些计数是 Owner 提供的实网核验结果，本次合成测试不冒充真实复验。

另核对副本 `PRAGMA integrity_check=ok`。分开核对两步保全：升级副本相对正式原库只增加六个日期触发器及 `meta.date_constraints`，全部历史数据不变；恢复副本与已升级的 `outputs/market-date-constraints-check.sqlite` 比对，除 H00300/raw、新 backfill run 和新 T01 coverage 外，各表历史行及 T01 全部 `exec_*` 字段应逐值一致。第二次恢复 apply 的 `idempotent=true`、`changed=false`，文件哈希不变。保留所有 JSON 和 Git commit 作为本机执行证据。真实库写入、缺行情修复和正式研究执行另行授权；本次不要自动接 build、研究命令、规则开关或 cron。

## 相关文件

- `src/data/offline_restore.py`：证据校验与原子恢复。
- `src/data/quality.py`：只读质量预检。
- `src/indicators/build.py`：正式 build 强制门禁。
