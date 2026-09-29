"""等权组合日收益的持久化（schema v1.1-e）：data/ledger/ew_daily.csv，列 date, ew_return, ew_level, n_containers，只追加。
卡片锁定创建当日的累计点位；容器集合以后变化时，旧点位不重算，冻结的反事实数值始终可复现。
当日收益 = 当日与上一个已记录日都有收盘的容器的收益均值（I-10 的等权口径）；第一天点位为 1。
path=None 时只在内存里记（测试用），不碰任何文件。"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EW_PATH = ROOT / "data" / "ledger" / "ew_daily.csv"
COLUMNS = ["date", "ew_return", "ew_level", "n_containers"]


class EwStore:
    def __init__(self, path: Path | None = EW_PATH):
        self.path = Path(path) if path is not None else None
        self.rows: dict[str, tuple[float, float, int]] = {}
        if self.path is not None and self.path.exists():
            with open(self.path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    self.rows[r["date"]] = (float(r["ew_return"]), float(r["ew_level"]), int(r["n_containers"]))

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
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists()
            with open(self.path, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                if new:
                    w.writerow(COLUMNS)
                w.writerow([key, repr(ret), repr(level), n])
        self.rows[key] = (ret, level, n)
        return level

    def first(self) -> str | None:
        return min(self.rows) if self.rows else None

    def series(self) -> pd.Series:
        return pd.Series({pd.Timestamp(d): v[1] for d, v in sorted(self.rows.items())}, dtype=float)
