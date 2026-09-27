"""prereg-v1 的全部参数与实现口径。

数值参数逐条对应 docs/etf-rotation-prereg-v1.md §3–§5、§7、§9；
prereg 没有写死、由实现补充的口径（I-xx）见
operations/planning/2026-09-27-prereg-v1-implementation-notes.md，须在接触真实数据前由 Owner 确认。
"""
from dataclasses import dataclass, field, replace

# 形态状态代码（src/rotation/etf_probe.py kell_states 的输出）
STATE_NAMES = {
    "POP": "启动", "XB": "回踩", "BNB": "平台突破", "REV": "超跌反弹",
    "EXH": "过热", "DROP": "破位", "XBD": "反弹遇阻", "BNBD": "平台跌破",
    "TREND_UP": "上升中", "TREND_DOWN": "下跌中", "NEUTRAL": "无趋势",
}
ENTRY_STATES = frozenset({"POP", "XB", "BNB"})          # prereg-v1 §3.1（I-01：不含 REV）
DANGER_STATES = frozenset({"EXH", "DROP", "XBD", "BNBD"})
NEUTRAL_STATES = frozenset({"TREND_UP", "TREND_DOWN", "NEUTRAL"})

DESIGN_END = "2015-12-31"
OOS_START = "2016-01-01"
OOS_END = "2026-09-30"


@dataclass(frozen=True)
class Params:
    # §3.1 入场（主分支：突破）
    entry_states: frozenset = ENTRY_STATES
    rs_top_pct: float = 0.20          # 新定自由度 1：近 1 月相对强弱前 20%
    cooldown_days: int = 20           # 同一容器 20 个交易日内不重复触发
    # §3.2 入场（次分支：恐慌）
    z_threshold: float = -2.0
    # §4 离场
    stop_atr: float = 2.0             # 新定自由度 2：失效位 = 信号日收盘 − 2 × ATR20
    trail_atr: float = 3.0            # 新定自由度 3：+1R 后 最高收盘 − 3 × ATR20
    activate_at_r: float = 1.0        # 浮盈达到 +1R 后启用移动止盈
    # §5 仓位
    risk_per_trade: float = 0.005     # 新定自由度 4：每笔 1R = 净值 0.5%
    max_weight: float = 0.25
    max_positions: int = 8
    max_total_risk: float = 0.04
    min_weight: float = 0.01          # I-08：现金不足时缩仓，低于 1% 净值则放弃
    # §6 成本
    cost_per_side: float = 0.0005
    index_discount_per_year: float = 0.01   # §2.3 指数 ≠ ETF，按每年 1% 打折（只用于报告）
    # §9 验收
    accept_mean_r: float = 0.15
    accept_min_trades: int = 200
    accept_min_positive_years: int = 6
    accept_years: tuple = tuple(range(2016, 2026))   # I-12：10 个完整年度，2026 单列
    # 刻画（§10 第 2 步，I-14 / I-15）
    char_horizon: int = 20
    char_bootstrap: int = 2000
    corr_window: int = 60
    null_reps: int = 200               # I-17：随机入场对照次数；Owner 不采用则设为 0

    def perturbed(self, name, factor):
        return replace(self, **{name: getattr(self, name) * factor})


PERTURB_PARAMS = ("rs_top_pct", "stop_atr", "trail_atr")   # §10 第 3 步：±20%
PERTURB_FACTORS = (0.8, 1.2)
