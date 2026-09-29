"""研究数据包 → V1 长表（implementation-notes §B）。

    python -m src.indicators build --package outputs/research-package-2026-09-30/ [--out outputs/panel-2026-09-30/]

输出 panel.csv（date, container, open, high, low, close, state, rs_1m, atr20, z_month）、bench.csv（date, hs300 = H00300）
和 build-report.json（每个容器的数据处理与缺陷计数）。之后跑
    python -m src.research.prereg_v1.run check --panel <out>/panel.csv --bench <out>/bench.csv
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import runner as data_runner
from .metrics import atr20, rs_1m, z_month
from .states import form_states

BENCH_CODE = "H00300"          # I-18：沪深300 全收益，不用价格指数 000300 顶替
PANEL_COLUMNS = ["date", "container", "open", "high", "low", "close", "state", "rs_1m", "atr20", "z_month"]
ROOT = Path(__file__).resolve().parents[2]


class BuildError(RuntimeError):
    pass


def load_series(path: Path) -> tuple[pd.DataFrame, dict]:
    """读 raw 序列并做最小修整，修了什么都计数进报告：
    - 开 / 高 / 低缺失或非正时用收盘补（EIA 布伦特只有收盘；ATR 因此退化为收盘到收盘的波幅）；
    - 高 / 低不包住开收时收紧到开收范围（build_hfq.py 对腾讯两位小数高低价的同一处理）。"""
    df = pd.read_csv(path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    n0 = len(df)
    df = df[df["close"] > 0].sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    rep = {"rows": len(df), "dropped_no_close_or_duplicate": n0 - len(df)}
    rep["ohl_filled_from_close"] = int((~(df[["open", "high", "low"]] > 0).all(axis=1)).sum())
    for c in ("open", "high", "low"):
        bad = ~(df[c] > 0)
        df.loc[bad, c] = df.loc[bad, "close"]
    hi, lo = df[["open", "high", "low", "close"]].max(axis=1), df[["open", "high", "low", "close"]].min(axis=1)
    rep["hl_clamped"] = int(((df["high"] < hi) | (df["low"] > lo)).sum())
    df["high"], df["low"] = hi, lo
    rep["volume_missing_or_zero"] = int((~(df["volume"] > 0)).sum())
    return df, rep


def container_panel(df: pd.DataFrame, bench: pd.Series, end: date) -> pd.DataFrame:
    st = form_states(df)
    return pd.DataFrame({
        "date": df["date"], "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
        "state": st["state"], "rs_1m": rs_1m(df["close"], df["date"], bench), "atr20": atr20(df),
        "z_month": z_month(df["close"], df["date"], end),
    })


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(package: Path, out: Path | None = None, *, log=print) -> Path:
    package = Path(package)
    problems = data_runner.verify(package)
    if problems:
        raise BuildError("研究数据包未通过 MANIFEST 复验：" + "; ".join(problems[:5]))
    meta = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    end = date.fromisoformat(meta["end"])
    out = Path(out) if out else ROOT / "outputs" / f"panel-{end.isoformat()}"
    cov = pd.read_csv(package / "coverage.csv", dtype=str).fillna("")

    bench_path = package / "raw" / f"{BENCH_CODE}.csv"
    if not bench_path.exists():
        raise BuildError(f"数据包里没有 {BENCH_CODE}（沪深300 全收益，I-18）；不以价格指数顶替")
    bdf, _ = load_series(bench_path)
    bench = bdf.set_index("date")["close"]

    frames, report = [], {"package": str(package), "end": end.isoformat(), "manifest_sha256": _sha256(package / "MANIFEST.sha256"),
                          "bench": {"code": BENCH_CODE, "first": str(bench.index.min().date()), "last": str(bench.index.max().date())},
                          "containers": {}, "skipped": {}}
    panel_rows = cov[cov["status"].isin(["retained", "flagged"])]
    for _, c in panel_rows.iterrows():
        name = c["container"]
        if not c["series_file"] or not (package / "raw" / c["series_file"]).exists():
            report["skipped"][name] = c["error"] or "无研究序列"
            log(f"  --  {name}: 跳过（{report['skipped'][name][:80]}）")
            continue
        df, rep = load_series(package / "raw" / c["series_file"])
        p = container_panel(df, bench, end)
        p.insert(1, "container", name)
        frames.append(p)
        a_dates = set(bench.index)
        rep.update(series_file=c["series_file"], route=c["route_used"], price_only=c["price_only"],
                   first=str(df["date"].min().date()), last=str(df["date"].max().date()),
                   states={k: int(v) for k, v in p["state"].value_counts().items()},
                   z_month_values=int(p["z_month"].notna().sum()),
                   dates_not_in_bench_calendar=int((~p["date"].isin(a_dates)).sum()))
        report["containers"][name] = rep
        log(f"  ok  {name}: {rep['rows']} 行 {rep['first']}→{rep['last']}"
            + (f"；无成交量 {rep['volume_missing_or_zero']} 行" if rep["volume_missing_or_zero"] else ""))
    if not frames:
        raise BuildError("没有任何容器有研究序列")
    panel = pd.concat(frames, ignore_index=True).sort_values(["date", "container"]).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    panel[PANEL_COLUMNS].to_csv(out / "panel.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame({"date": bench.index, "hs300": bench.to_numpy()}).to_csv(out / "bench.csv", index=False, date_format="%Y-%m-%d")
    report["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["panel_sha256"], report["bench_sha256"] = _sha256(out / "panel.csv"), _sha256(out / "bench.csv")
    (out / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"  面板 {len(panel)} 行、{len(frames)} 个容器 → {out}")
    return out


# ------------------------------------------------------------------ 与历史产物对照
def legacy_check(data_dir: Path, *, tol: float = 1e-9) -> dict:
    """用仓库 09-25 快照（data/kline_<code>.csv + data/panel_daily.csv，由 src/rotation/analyze.py 生成）重算，
    逐日比对 state（旧名 kell）、ext 与 rs_1m。只比较字段，不产出任何研究结论。"""
    data_dir = Path(data_dir)
    legacy = pd.read_csv(data_dir / "panel_daily.csv", parse_dates=["date"], dtype={"code": str})
    bench = pd.read_csv(data_dir / "kline_510300.csv", parse_dates=["date"]).set_index("date")["close"]
    res = {}
    for code, g in legacy.groupby("code"):
        h = pd.read_csv(data_dir / f"kline_{code}.csv", parse_dates=["date"]).reset_index(drop=True)
        st = form_states(h)
        mine = pd.DataFrame({"date": h["date"], "state": st["state"], "ext": st["ext"], "rs_1m": rs_1m(h["close"], h["date"], bench)})
        m = g[["date", "kell", "ext", "rs_1m"]].merge(mine, on="date", how="left", suffixes=("_legacy", ""))
        num = lambda a, b: int((~(np.isclose(m[a], m[b], atol=tol, equal_nan=True))).sum())   # noqa: E731
        res[code] = {"rows": len(m), "state_diff": int((m["kell"] != m["state"]).sum()),
                     "ext_diff": num("ext_legacy", "ext"), "rs_1m_diff": num("rs_1m_legacy", "rs_1m")}
    return res
