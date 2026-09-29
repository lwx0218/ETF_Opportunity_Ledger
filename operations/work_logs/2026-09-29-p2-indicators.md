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
| 测试 | `python -m unittest discover -s tests -t .`：91 个全过（原 31 + 数据层 47 + 指标层 13） |
| 包末复核 | `approve_with_follow_up`：状态机与 kell_states 函数体逐行相同；z_month 与 characterize.py 口径对比 239 个值差为 0；183 个截断点无未来函数；CLI build → run check → characterize 可读 |

## 交付

- `src/indicators/states.py`（状态机）、`metrics.py`（ATR20、rs_1m、z_month、月末判定）、`build.py`（数据包 → panel.csv / bench.csv / build-report.json；legacy-check）、`__main__.py`。
- `tests/indicators/test_indicators.py`；`docs/indicators-layer.md`。

## 复核发现与处理

| # | 发现 | 处理 |
|---|---|---|
| 1 中 | 混合交易日历让等权基准漏掉跨假期收益、A 股休市日横截面退化、回测里有做不到的交易 | 研究口径，交 Cowork 二选一（对齐到 A 股日历 / 改 prereg_v1 按各自日历），**须在数据包到达、characterize 之前定**；影响已写进 `docs/indicators-layer.md` |
| 2 中 | 无成交量的序列不会出现「启动」等四态 | 研究口径，交 Cowork 定成交量来源（可借价格版本），V1 前定；定后本层小改动实现 |
| 3 低 | 月末判定依赖 end：停更序列月中冒 z、周末月末当天认不出（P5 会漏恐慌信号） | 最后一行改为「下一个工作日已进入新月份」才算月末；加测试 |
| 4 低 | 非正收盘被静默丢弃，下游负价防线失效 | 收盘非正直接报错；缺收盘与重复日期分开计数 |
| 5 低 | 修整计数只在 JSON 里 | 非零计数全部打印到日志；文档措辞改为「扩到包住开收」 |
| 6 待办 | 真实快照上的 legacy-check、Cowork 复核 | 保留为待办 |

## 待决

见 `docs/indicators-layer.md`「已知局限」。
