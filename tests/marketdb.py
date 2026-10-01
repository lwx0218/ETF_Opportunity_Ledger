"""测试用的临时行情库（replan §11：测试只许连临时库）：写序列、写 coverage。"""
import pandas as pd

from src.data import db as DB
from src.data import store


def open_db(path):
    return DB.connect(path)


def put(con, code: str, df: pd.DataFrame, route: str) -> None:
    """DataFrame（date 为日期或字符串）整条写成序列 (code, adj_of(route))。"""
    rows = [{**r, "date": pd.Timestamp(r["date"]).date().isoformat()} for r in df.to_dict("records")]
    store.replace(con, code, route, rows, "test")


def put_coverage(con, rows: list[dict], kind: str = "backfill") -> int:
    run = DB.start_run(con, kind)
    DB.write_coverage(con, run, rows)
    DB.finish_run(con, run)
    return run
