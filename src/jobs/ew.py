"""等权组合日收益的持久化（schema v1.1-e）：台账库内的 ew_daily 表（replan §11：原「库旁文件」改为库内表，两者天然成对），
列 date, ew_return, ew_level, n_containers，只追加（存储层触发器核对日期递增与点位连乘）。
卡片锁定创建当日的累计点位；容器集合以后变化时，旧点位不重算，冻结的反事实数值始终可复现。
当日收益 = 当日与上一个已记录日都有收盘的容器的收益均值（I-10 的等权口径）；第一天点位为 1。"""
from __future__ import annotations

import pandas as pd

from src.ledger.store import Ledger


class EwStore:
    def __init__(self, ledger: Ledger):
        self.L = ledger
        self.rows: dict[str, tuple[float, float, int]] = ledger.ew_rows()

    def ensure(self, panel: pd.DataFrame, day: pd.Timestamp) -> float | None:
        """记下 day 的等权收益与点位（已记过则直接返回）。只能按日期向后追加：比最后一条更早且没记过的日子返回 None。"""
        key = day.date().isoformat()
        if key in self.rows:
            return self.rows[key][1]
        last = max(self.rows) if self.rows else None
        if last and key < last:
            return None
        today = panel[panel["date"] == day].set_index("container")["close"]
        if today.empty:
            return None
        if last is None:
            ret, level, n = 0.0, 1.0, int(today.notna().sum())
        else:
            prev = panel[panel["date"] == pd.Timestamp(last)].set_index("container")["close"]
            both = pd.concat([prev, today], axis=1, join="inner").dropna()
            r = both.iloc[:, 1] / both.iloc[:, 0] - 1
            ret, n = (float(r.mean()) if len(r) else 0.0), len(r)
            level = self.rows[last][1] * (1 + ret)
        self.L.record_ew(key, ret, level, n)
        self.rows[key] = (ret, level, n)
        return level

    def first(self) -> str | None:
        return min(self.rows) if self.rows else None

    def series(self) -> pd.Series:
        return pd.Series({pd.Timestamp(d): v[1] for d, v in sorted(self.rows.items())}, dtype=float)
