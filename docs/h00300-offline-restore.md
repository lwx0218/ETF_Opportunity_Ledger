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

## 只读预检与正式 build

```bash
python -m src.data preflight --db data/market.sqlite --end 2026-09-30
```

JSON 报告分别给出 `benchmark_ready`、`research_ready`，以及每个容器的缺收盘日期、缺 OHLC 日期、被计算视图排除的非交易日与原因。退出码 0 表示 `research_ready=true`；质量阻断返回 1，JSON 仍是有效报告。

默认检查窗口为 2005-01-01 至 `--end`；单独诊断可用 `--start`，不会改变正式 build 的固定起点。要求库内官方 `calendar` 覆盖窗口，不由 H00300 日期反推交易日，不退回工作日历。元旦名义起点允许官方首个交易日在其后 14 天内（沿用日历结构校验的最大间隔）；官方日历的真实性仍以上游 S1 证据为准。

- 基准：官方窗口每个交易日都必须有正、有限的 H00300 原始收盘。开高低缺失可单独报告，不影响 `benchmark_ready`。首尾缺日也阻断，不按行情实际终点缩短检查。
- 研究：对 universe 与 coverage 声明的全部 retained/flagged 容器检查，缺 coverage 或序列不自动跳过。A 股序列从其登记起点起检查至窗口末尾；缺交易日真实收盘阻断。策略必须有正、有限的原始 OHLC，不得把收盘补成开高低后放行。T01 既是基准来源又是研究容器，因此可以基准就绪而研究未就绪。
- 海外序列检查其原生 OHLC，包含窗口前用于 I-24 指标预热的已有历史（`native_warmup_rows`），不截掉预热来通过校验。仍沿用现有 D−1 对齐和休市/断档规则，不要求每个 A 股交易日都有一根海外原始 K 线。成交量缺失仍按已有 I-21 报告，本包不变更参数或海外断档规则。
- `python -m src.indicators build --package ...` 在包哈希复验后、指标计算和任何面板写入前执行同一预检。阻断时打印完整质量报告并失败，已有面板不改；通过后计算视图按官方日历过滤国内非交易日，基准读取真实收盘，原始包与库保持不变。成功报告包含 `input_quality`。

本包只接正式研究 build；每日任务 live 路径的后续改造属于另包，不借本任务推进 P6g。

容器可得起点以 coverage 与原始行情中较早的日期为准；这不是对指数上市史或回填历史完整性的外部证明。基准始终按完整官方窗口检查，不因 coverage 缩短而放行。

## pi 执行说明

开发环境没有服务器原响应，以下真实恢复必须由 pi 在服务器离线执行。先进入项目并激活服务器已有的 Python 环境。使用独立验证副本，勿直接对真实库 apply：

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
src = sqlite3.connect(Path('data/market.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
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

另核对副本 `PRAGMA integrity_check=ok`，并与原库比对：除 H00300/raw、新 backfill run 和新 T01 coverage 外，各表历史行及 T01 全部 `exec_*` 字段应逐值一致；第二次 apply 的 `idempotent=true`、`changed=false`，文件哈希不变。保留所有 JSON 和 Git commit 作为本机执行证据。真实库写入、缺行情修复和正式研究执行另行授权；本次不要自动接 build、研究命令、规则开关或 cron。

## 相关文件

- `src/data/offline_restore.py`：证据校验与原子恢复。
- `src/data/quality.py`：只读质量预检。
- `src/indicators/build.py`：正式 build 强制门禁。
