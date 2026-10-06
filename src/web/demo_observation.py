"""供两页演示使用的内存行情；不读取正式行情、台账或规则。

工作日、价格、量和获取时间全是合成样例，不是官方行情或日历。
六个台账演示容器在 DAYS 内沿用 demo.synthetic_panel 的同一价格公式；
提前保留 600 个工作日仅供指标预热，不改变台账演示或策略参数。
"""
from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator

import pandas as pd

from src.data import db as DB
from src.data.universe import PANEL_STATUSES, UNIVERSE
from src.web.demo import DAYS, INSTRUMENTS


SOURCE = "demo_synthetic"
FETCHED_AT = "2026-08-03T08:00:00+00:00"  # 合成记录时刻，不声称发生过抓取。
WARMUP = 600


@contextmanager
def demo_market() -> Iterator[sqlite3.Connection]:
    """返回独立且 query_only 的 market-v1 内存库，时点截断交给观察模型。

只读取版本控制中的容器声明 CSV；实际行情、台账、规则和磁盘 SQLite
连接均不参与。关闭 context 即释放全部合成数据，不产生市场库文件。
    """
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.executescript(DB.SCHEMA)
        con.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("schema", DB.SCHEMA_VERSION),
            ("observation_mode", "synthetic"),
            ("calendar_basis", "合成工作日，非官方交易日历"),
            ("fetched_at_basis", "合成记录时刻；未发生行情抓取"),
        ])
        dates = pd.bdate_range(end=DAYS[-1], periods=WARMUP + len(DAYS))
        days = tuple(d.date().isoformat() for d in dates)
        con.executemany("INSERT INTO calendar VALUES (?)", ((d,) for d in days))
        con.execute("INSERT INTO runs(run_id,kind,started_at,end_date,args,status) "
                    "VALUES (1,'backfill',?,?,?,'ok')",
                    (FETCHED_AT, days[-1], json.dumps({"synthetic": True})))
        with UNIVERSE.open(encoding="utf-8", newline="") as file:
            rows = [row for row in csv.DictReader(file) if row["status"] in PANEL_STATUSES]
        demo_order = {name: index for index, name in enumerate(INSTRUMENTS)}
        for index, row in enumerate(rows):
            name, tid = row["theme"], row["theme_id"]
            instrument = INSTRUMENTS.get(name, {})
            research_code = "H00300" if tid == "T01" else instrument.get("research_code", f"DEMO-{tid}-TR")
            exec_code = instrument.get("code", f"DEMO-{tid}")
            row.update(research_index_code=research_code, research_index_name=f"{name} · 合成研究序列",
                       research_route=SOURCE, tr_code_candidates=research_code,
                       execution_fund_code=exec_code, execution_fund_name=f"{name} · 合成执行价格",
                       execution_alternatives="", identity_source="合成演示；不代表真实指数或 ETF",
                       open_question="合成量的真实单位未核定；不是正式研究资格证明")
            con.execute("INSERT INTO universe VALUES (?, ?, ?)",
                        (index, tid, json.dumps(row, ensure_ascii=False)))
            coverage = dict(container=name, code=research_code, route_used=SOURCE,
                            first_date=days[0], last_date=days[-1], rows=len(days),
                            tr_code_used=research_code, price_only="false", theme_id=tid,
                            status=row["status"], series_code=research_code, series_adj="raw",
                            series_name=row["research_index_name"], price_first_date=days[0],
                            ohlc_missing_rows=0, volume_missing_rows=0,
                            exec_code=exec_code, exec_route=SOURCE, exec_first_date=days[0],
                            exec_last_date=days[-1], exec_rows=len(days), checked_at=FETCHED_AT,
                            notes="合成 OHLCV；量单位未核定；日历为工作日样例")
            columns = DB.COVERAGE_COLUMNS
            con.execute(f"INSERT INTO coverage(run_id,{','.join(columns)}) "
                        f"VALUES (1,{','.join('?' for _ in columns)})",
                        tuple(str(coverage.get(key, "")) for key in columns))
            if name in demo_order:
                j = demo_order[name]
                base, step, volume = 100 + 10 * j, .12 + .01 * j, 1000000 + 10000 * j
            elif tid == "T01":
                base, step, volume = 4000, 1, 2000000
            else:
                base, step, volume = 250 + 10 * index, .06 + .004 * index, 1500000 + 10000 * index
            values = []
            for offset, day in enumerate(days, start=-WARMUP):
                close = base + offset * step
                values.append((day, close - step, close + 1, close - step - 1,
                               close, volume, None, SOURCE, FETCHED_AT))
            for code in (research_code, exec_code):
                con.executemany("INSERT INTO bars VALUES (?, 'raw', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                ((code, *value) for value in values))
        con.commit()
        con.execute("PRAGMA query_only = ON")
        yield con
    finally:
        con.close()
