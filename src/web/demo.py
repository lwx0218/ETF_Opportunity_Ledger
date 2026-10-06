"""隔离、可重现的流程演示；所有行情与判断均为合成样例，不读真实行情。"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.indicators.metrics import atr20, rs_1m, z_month
from src.indicators.states import form_states
from src.jobs.daily import DailyJob
from src.ledger.store import DEFAULT_DB, ROOT, SCHEMA_VERSION, Ledger, LedgerError


DEMO_VERSION = "web-demo-v2"
DAYS = tuple(d.date().isoformat() for d in pd.bdate_range("2026-08-03", periods=90))
INITIAL_DAY = DAYS[30]
INSTRUMENTS = {
    name: {"code": f"DEMO-{code}", "name": f"{name} · 合成演示", "research_code": f"DEMO-{code}-TR"}
    for name, code in (("原油", "OIL"), ("农业", "FARM"), ("黄金", "GOLD"),
                       ("半导体", "CHIP"), ("国债", "BOND"), ("红利", "DIV"))
}
SOURCES = {"原油": "ENE-EIA-WPSR", "农业": "AGR-USDA-WASDE", "黄金": "PM-SAFE-ORA",
           "半导体": "TEC-TSMC-MREV", "国债": "CN-CHINABOND-YC", "红利": "CN-XINHUA-POLICY"}


def synthetic_panel() -> tuple[pd.DataFrame, pd.Series]:
    """用现有指标与状态机计算合成 OHLCV；工作日不是官方交易日历。

    预热覆盖状态机最长的 SMA200 窗口，再裁到演示日。月末历史不足
    20 个月时 z_month 保留 NaN；不填补指标，不改变策略参数。
    """
    dates = pd.bdate_range(end=DAYS[-1], periods=200 + len(DAYS))
    offsets = pd.Series(range(-200, len(DAYS)))
    bench = pd.Series(4000 + offsets.to_numpy(), index=dates, dtype=float)
    panels = []
    for j, name in enumerate(INSTRUMENTS):
        step = 0.12 + j * 0.01
        close = 100 + 10 * j + offsets * step
        frame = pd.DataFrame({"date": dates, "container": name, "open": close - step,
                              "high": close + 1, "low": close - step - 1, "close": close,
                              "volume": 1000000 + 10000 * j, "data_hole": 0})
        frame["atr20"] = atr20(frame)
        frame["rs_1m"] = rs_1m(frame["close"], frame["date"], bench)
        frame["z_month"] = z_month(frame["close"], frame["date"], dates[-1].date(), trading_days=dates)
        frame["state"] = form_states(frame)["state"]
        panels.append(frame.loc[frame["date"] >= pd.Timestamp(DAYS[0])])
    return pd.concat(panels, ignore_index=True), bench.loc[DAYS[0]:]


def _draft(name: str) -> dict:
    return {
        "container": name, "thesis": f"演示：以{name}合成序列练习冻结判断，尚无真实事件证据。",
        "evidence_status": "已检索无证据", "evidence": [],
        "agent_score": {"score": 2, "reason": "演示评分：固定源中未放入任何真实证据，不代表投资判断。"},
        "expectation": {"horizon_days": 20, "target_excess_pct": 3, "benchmark": "等权组合"},
        "thesis_invalidation": {"source_id": SOURCES[name], "deadline": DAYS[55],
                                "statement": "仅为演示：到观察日仍无可核验证据，声明论点作废；未声称该源已发布事件。"},
    }


class DemoStore:
    """固定文件与单库时钟。调用方负责串行化请求；每次操作独立连接。"""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory).resolve()
        self.path = self.directory / "ledger.sqlite"
        self._check_path()

    def _check_path(self):
        if self.directory.is_relative_to((ROOT / "data").resolve()) or self.path.is_symlink():
            raise LedgerError("演示库不能指向 data 目录或符号链接")
        for formal in (DEFAULT_DB, ROOT / "data" / "market.sqlite"):
            if self.path.exists() and formal.exists() and self.path.samefile(formal):
                raise LedgerError("演示库不能指向正式库或其文件别名")

    def _validate(self) -> str:
        self._check_path()
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as con:
                meta = dict(con.execute("SELECT key, value FROM ledger_meta"))
                if (meta.get("web_demo") != DEMO_VERSION or meta.get("clock") != "replay"
                        or meta.get("schema") != SCHEMA_VERSION):
                    raise LedgerError("该文件不是本应用的隔离演示库，拒绝写入或重置")
                day = con.execute("SELECT max(day) FROM job_days").fetchone()[0]
        except sqlite3.DatabaseError as e:
            raise LedgerError("无法读取隔离演示库；不会覆盖已有文件") from e
        if day not in DAYS or day < INITIAL_DAY:
            raise LedgerError("演示时钟缺失或超出本版本范围，拒绝写入")
        return day

    def ensure(self):
        if self.path.exists():
            self._validate()
        else:
            self.reset()

    def now(self) -> str:
        return f"{self._validate()}T16:00"

    @contextmanager
    def open_ledger(self):
        self._validate()
        ledger = Ledger(self.path, clock=self.now, replay=True)
        try:
            yield ledger
        finally:
            ledger.close()

    @contextmanager
    def _staging(self):
        self._check_path()
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".demo-", dir=self.directory) as tmp:
            yield Path(tmp) / "ledger.sqlite"

    @staticmethod
    def _job(ledger, panel, bench, events_dir=None):
        # 仅此合成输入在内存中启用事件流程；不加载、更不改变正式规则配置。
        return DailyJob(ledger, panel, bench, rules={"事件驱动": {}}, instruments=INSTRUMENTS,
                        events_dir=events_dir, trading_days=pd.to_datetime(DAYS))

    def reset(self) -> dict:
        if self.path.exists():
            self._validate()
        with self._staging() as staging:
            panel, bench = synthetic_panel()
            events = staging.parent / "events"
            events.mkdir()
            for index, names in ((0, ("原油", "农业")), (24, ("黄金",)), (26, ("半导体",)),
                                 (30, ("国债", "红利"))):
                (events / f"{DAYS[index]}.json").write_text(
                    json.dumps([_draft(name) for name in names], ensure_ascii=False), encoding="utf-8")
            clock = f"{DAYS[0]}T16:00"
            ledger = Ledger(staging, clock=lambda: clock, replay=True)
            try:
                job = self._job(ledger, panel, bench, events)
                for i, day in enumerate(DAYS[:31]):
                    clock = f"{day}T16:00"
                    report = job.run(day)
                    if report.blocked or report.skipped:
                        raise LedgerError(f"演示初始化失败：{report.blocked or report.skipped}")
                    if i == 0:
                        ledger.void("T-2026-002", "演示：候选未进场即作废，仍保留在分母。")
                    if i in (2, 27):
                        cid = "T-2026-001" if i == 2 else "T-2026-003"
                        row = ledger.daily_rows(cid)[-1]
                        ledger.signal_exit(cid, day, "手动" if i == 2 else "论点作废", row["close"],
                                           "演示：声明离场，下一合成交易日才成交。" if i == 2 else None)
                    ledger.mark_processed(day)
                ledger.conn.execute("INSERT INTO ledger_meta VALUES ('web_demo', ?)", (DEMO_VERSION,))
            finally:
                ledger.close()
            os.replace(staging, self.path)
        return {"day": INITIAL_DAY, "now": self.now(), "reset": True}

    def advance(self) -> dict:
        day = self._validate()
        index = DAYS.index(day) + 1
        if index == len(DAYS):
            raise LedgerError("本段演示已结束，可重置后重新体验；未继续生成行情")
        next_day = DAYS[index]
        with self._staging() as staging:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(staging)) as target:
                    source.backup(target)
            ledger = Ledger(staging, clock=lambda: f"{next_day}T16:00", replay=True)
            try:
                panel, bench = synthetic_panel()
                report = self._job(ledger, panel, bench).run(next_day)
                if report.blocked:
                    raise LedgerError(report.blocked)
                ledger.mark_processed(next_day)
            finally:
                ledger.close()
            os.replace(staging, self.path)
        return asdict(report)
