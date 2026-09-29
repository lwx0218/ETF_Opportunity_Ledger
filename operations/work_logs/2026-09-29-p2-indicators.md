# P2 · 指标层 `src/indicators/`

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: replan §3 P2——状态机抽出、ATR20、rs_1m、z_month → V1 长表 + 基准表
- Timestamp (UTC): 2026-09-29
- Owner: Faye
- Executor: Claude Code（云端）；包末复核：只读 reviewer 子代理
- Route: direct-execute（Owner 指示按 replan §3 顺序推进）
- Source of truth: replan §3 P2；implementation-notes I-02、I-18、B 节；`tests/research/test_prereg_v1.py::test_no_lookahead` 的做法

## 结果

| 完成判据 | 结果 |
|---|---|
| 与历史产物一致 | 构造数据上：新状态机与 `kell_states` 逐日完全一致（5 个种子，含 EMA、ATR14、ext）；`legacy-check` 对 analyze.py 格式的构造快照 state / ext / rs_1m 差异为 0。**真实 09-25 快照（`data/kline_*.csv`、`data/panel_daily.csv`）不在 Git、本环境没有，需在有数据的机器上跑 `python -m src.indicators legacy-check`** |
| 无未来函数 | 截断测试：4 个截断点，删掉之后的数据，之前每一行每一列不变 |
| `run check` 能通过 | 构造数据包 → build → `python -m src.research.prereg_v1.run check` 返回 0 |
| Cowork 研究逻辑复核 | 待 Cowork（只读 diff） |
| 测试 | `python -m unittest discover -s tests -t .`：89 个全过（原 31 + 数据层 47 + 指标层 11） |

## 交付

- `src/indicators/states.py`（状态机）、`metrics.py`（ATR20、rs_1m、z_month、月末判定）、`build.py`（数据包 → panel.csv / bench.csv / build-report.json；legacy-check）、`__main__.py`。
- `tests/indicators/test_indicators.py`；`docs/indicators-layer.md`。

## 待决

见 `docs/indicators-layer.md`「已知局限」：无成交量序列的状态、海外交易日历、Cowork 复核。
