# P1 · 数据层 `src/data/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §3 P1——数据层代码 + probe（数据源可用性的最小验证）
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Executor: Claude Code（云端）
- Route: direct-execute（Owner 指示「按 §3 从 P1 开始，P1 先交 probe」）
- Source of truth: `operations/planning/2026-09-29-replan-three-lanes.md` §3 P1、§6；`data/universe.csv` v1；AGENTS.md

## 结果

| 项 | 结果 |
|---|---|
| probe 实跑（CC 云端，`--end 2026-09-29`） | 39 行；面板容器 37 个：有路由 **0**，明确 error **37**；T29 已剔除不拉取；T34 只查执行序列（也失败） |
| 失败原因 | 出网策略拒绝：7 个行情域名的 CONNECT 均被代理 403（csindex、oss-ch.csindex、gtimg、eastmoney push2his、Yahoo、stooq、eia）；T15 另记 `EIA_API_KEY 未设置` |
| 请求记录 | 167 次请求，全部失败，逐条写入 `outputs/data/probe-requests.jsonl`（sha256 `7d5ea574…`）；coverage.csv sha256 `f7a18a23…`（均不入 Git） |
| 单元测试 | `python -m unittest discover -s tests -t .`：65 个全过（原 31 + 数据层 34） |
| 完成判据「37 个面板容器每个有 route_used 或明确 error」 | 形式上满足；**实质判据（有路由）须在服务器上重跑 probe**（astra S1） |

## 交付

- `src/data/`：`http.py`（标准库、至多重试一次、请求留痕）、`sources.py`（中证 / 东财 / 腾讯 / Yahoo / stooq / EIA）、`universe.py`（路由链与代码映射）、`store.py`（raw 读写与防拼接合并）、`runner.py` + `__main__.py`（probe / backfill / update / package / verify / compare）。
- `tests/data/`：fixtures 解析、分段、回退、全收益识别、声明替代、近似指数不采用、增量修正、打包截断与 MANIFEST 复验、qfq 差值阶跃。
- `docs/data-layer.md`：取数方式补记、研究序列选择规则、文件与字段。

## 与 replan 的差异与待决

1. **fixtures 是构造的，不是录制的**：出网被拒，无法录制。格式依据见 `tests/data/fixtures/README.md`；astra 首次跑 `probe --record outputs/data/recorded/` 后替换。
2. **纳指科技**：universe v1 写「拉不到 NDXTMC 就用 ^NDXT 代研究序列」，与 AGENTS.md「不用近似指数替代」冲突；代码按 AGENTS.md 只探测不采用，待 Cowork 定。
3. **创业板R 类名称**：全收益识别按 replan 字面规则（名称含全收益 / 财富 / Total Return，另加英文 TR）；深交所「xxxR」不会自动采用，名称写进 notes。
4. **EIA**：用 API v2（需免费 key，域名 `api.eia.gov`，不在 replan 白名单里）；无 key 时退到 Yahoo `BZ=F`，两者不拼接。
5. **09-14 腾讯快照比对**：`data/kline_*.csv` 不在 Git，本环境无数据；`compare` 命令已备好，随 S1 执行。

## 下一步

- Faye：在 CC 环境的网络设置里加行情域名（或由 astra 跑 S1）；需要布伦特现货时给服务器配 `EIA_API_KEY`。
- astra S1：`probe --record` → `backfill --end 2026-09-30` → `package --end 2026-09-30` → `verify`；coverage 里每个 error 一行，不逐条补证。
