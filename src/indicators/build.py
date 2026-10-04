"""研究数据包 → V1 长表（implementation-notes §B）。

    python -m src.indicators build --package outputs/research-package-2026-09-30.sqlite [--out outputs/panel-2026-09-30.sqlite]

输出一个库 panel-D.sqlite：panel 表（date, container, open, high, low, close, state, rs_1m, atr20, z_month, data_hole）、
bench 表（date, hs300 = H00300 收盘, hs300_open = 原始开盘，缺则空；每日任务的基准窗口用）、meta 表；
旁边 panel-D.build-report.json（每个容器的数据处理与缺陷计数）。全收益指数借价格版本的成交量（I-21），K 线级指标（state、atr20）在容器
原生序列上算（I-24），再对齐到 A 股日历（I-20）；rs_1m、z_month 在对齐后的收盘上算。之后跑
    python -m src.research.prereg_v1.run check --panel outputs/panel-2026-09-30.sqlite
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import db as DB
from src.data import runner as data_runner
from src.data import quality
from .calendar import load_trading_days
from .metrics import atr20, rs_1m, z_month
from .states import form_states

BENCH_CODE = "H00300"          # I-18：沪深300 全收益，不用价格指数 000300 顶替
OVERSEAS_ROUTES = {"yahoo", "stooq", "eia"}      # I-20：本地日期晚于 A 股收盘的路由，取 D−1
VOLUME_BORROW_SHARE = 0.5      # I-21：研究序列缺成交量的行超过一半就借价格版本
PANEL_COLUMNS = ["date", "container", "open", "high", "low", "close", "state", "rs_1m", "atr20", "z_month", "data_hole"]
BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
INDICATOR_COLUMNS = ["state", "atr20"]            # I-24：在原生 K 线上算、随 K 线带到 D 的列
MARK_COLUMNS = ["stale", "data_hole"]              # 对齐时打的标记：平盘行（I-20）、数据断档（I-25）
HOLE_MIN = 5                                       # I-25：连续平盘到第 5 行即为数据断档（真实休市最长 4 个交易日）
ROOT = Path(__file__).resolve().parents[2]
PANEL_SCHEMA_VERSION = "panel-v1"
PANEL_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE panel (
    date      TEXT NOT NULL CHECK (date(date) IS date),
    container TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    state     TEXT,
    rs_1m REAL, atr20 REAL, z_month REAL,
    data_hole INTEGER NOT NULL CHECK (data_hole IN (0, 1)),
    PRIMARY KEY (date, container)
) WITHOUT ROWID;
CREATE TABLE bench (
    date       TEXT PRIMARY KEY CHECK (date(date) IS date),
    hs300      REAL NOT NULL,
    hs300_open REAL
) WITHOUT ROWID;
"""


class BuildError(RuntimeError):
    pass


def read_bars(con, code: str, adj: str) -> pd.DataFrame:
    """bars 表里的一条序列（date 为 datetime64，数值缺失为 NaN），按日期升序。"""
    return _bar_frame(con.execute("SELECT date, open, high, low, close, volume FROM bars WHERE code = ? AND adj = ? ORDER BY date",
                                  (code, adj)).fetchall())


def _bar_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=BAR_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    for c in BAR_COLUMNS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def load_series(con, code: str, adj: str, *, frame=None, strict=False) -> tuple[pd.DataFrame, dict]:
    """读库里的序列并做最小修整，修了什么都计数进报告：
    - 开 / 高 / 低缺失或非正时用收盘补（EIA 布伦特只有收盘；ATR 因此退化为收盘到收盘的波幅）；
    - 高 / 低没有包住开收时，把高低价扩到包住开收（build_hfq.py 对腾讯两位小数高低价的同一处理）；
    - 收盘缺失的行丢弃；收盘非正直接报错。"""
    df = read_bars(con, code, adj) if frame is None else frame.copy()
    if strict and not np.isfinite(df[["open", "high", "low", "close"]]).all(axis=None):
        raise BuildError(f"{code}/{adj}: 策略需要真实 OHLC，不允许缺失或非有限值")
    if strict and not (df[["open", "high", "low", "close"]] > 0).all(axis=None):
        raise BuildError(f"{code}/{adj}: 策略需要正值 OHLC")
    bad = df["close"].notna() & ~(df["close"] > 0)
    if bad.any():          # P1 从不请求减法前复权：出现非正收盘就是数据坏了，不静默丢掉（也让下游的负价防线有意义）
        raise BuildError(f"{code}/{adj}: {int(bad.sum())} 行收盘非正（首个 {df.loc[bad, 'date'].iloc[0].date()}）")
    n_missing = int(df["close"].isna().sum())
    df = df[df["close"].notna()].sort_values("date")
    n_dup = int(df["date"].duplicated(keep="last").sum())
    df = df.drop_duplicates("date", keep="last").reset_index(drop=True)
    rep = {"rows": len(df), "dropped_missing_close": n_missing, "dropped_duplicate_dates": n_dup}
    rep["ohl_filled_from_close"] = int((~(df[["open", "high", "low"]] > 0).all(axis=1)).sum())
    for c in ("open", "high", "low"):
        bad = ~(df[c] > 0)
        df.loc[bad, c] = df.loc[bad, "close"]
    hi, lo = df[["open", "high", "low", "close"]].max(axis=1), df[["open", "high", "low", "close"]].min(axis=1)
    rep["hl_clamped"] = int(((df["high"] < hi) | (df["low"] > lo)).sum())
    df["high"], df["low"] = hi, lo
    rep["volume_missing_or_zero"] = int((~(df["volume"] > 0)).sum())
    return df, rep


def borrow_volume(df: pd.DataFrame, con, cov: dict) -> tuple[pd.DataFrame, str]:
    """I-21：研究序列缺成交量的行超过一半时，按日期换成同一指数价格版本（coverage.code 在库里的 raw 序列）的成交量。
    价格版本成份与交易日相同，成交量本是同一个数；放量条件是比值，单位无关。价格版本也没有成交量则保持原样。
    返回 (df, volume_source ∈ self / price_version / none)。"""
    if df.empty or (~(df["volume"] > 0)).mean() <= VOLUME_BORROW_SHARE:
        return df, "self"
    code = cov.get("code") or ""
    if not code or cov.get("series_code") == code:           # 研究序列就是价格版本本身（或研究 = 执行的后复权 ETF）
        return df, "none"
    pv = read_bars(con, code, "raw")                          # 价格版本不走后复权路由
    if pv.empty:
        return df, "none"
    vol = pd.Series(pv["volume"].to_numpy(), index=pv["date"])
    got = df["date"].map(vol)
    if not (got > 0).any():
        return df, "none"
    return df.assign(volume=got.where(got > 0, 0.0).to_numpy()), "price_version"


def align_to_calendar(df: pd.DataFrame, cal: pd.DatetimeIndex, overseas: bool) -> tuple[pd.DataFrame, dict]:
    """I-20：全部容器对齐到 A 股日历（H00300 的交易日）。
    - A 股路由：不在 A 股日历上的行丢弃并计数；首末日期之间日历上有、序列里缺的交易日不补，只计数（missing_on_calendar），
      这些日子的收益在等权里会缺席；
    - 海外路由：A 股交易日 D 取本地日期 ≤ D−1 的最后一根 K 线（美股 / 港股收盘都晚于 A 股 15:00，取 D−1 才无未来视角）；
      没有新 K 线（海外休市）写平盘 K 线：开高低收 = 前收，成交量 0，计 stale_days。
      两个 A 股交易日之间有多根新 K 线时（A 股长假）只用最后一根，计 multi_bar_days——跨假期收益落在这一根的收盘里。
      last_bar_date 是最后一行实际用到的 K 线日期（停更时远早于 D）。
    df 里的指标列（INDICATOR_COLUMNS，I-24：原生序列上算好的）随 K 线一起带到 D；平盘行沿用上一行的值。其他非 K 线列不带。
    另加两列标记（MARK_COLUMNS）：stale = 平盘行；data_hole = 连续平盘数到第 HOLE_MIN 行起为 1（I-25）。只看 ≤ D 的行：
    D 日还不知道这段平盘会不会延长，前 4 行与真实休市无法区分，按休市处理。报告里 stale_runs / max_stale_run 是事后整段统计。"""
    if not overseas:
        on = df["date"].isin(cal)
        kept = df[on].reset_index(drop=True).assign(stale=0, data_hole=0)
        span = cal[(cal >= kept["date"].min()) & (cal <= kept["date"].max())] if len(kept) else cal[:0]
        return kept, {"calendar": "a_share", "dropped_off_calendar": int((~on).sum()),
                      "missing_on_calendar": int((~span.isin(kept["date"])).sum())}
    src = df.sort_values("date").reset_index(drop=True)
    dates = src["date"].to_numpy()
    extra = [c for c in INDICATOR_COLUMNS if c in src.columns]       # 只带指标列；amount / source 这类列不带（平盘行对不上）
    rows, flat, multi, prev = [], [], 0, None
    for d in cal:
        i = int(np.searchsorted(dates, d.to_datetime64(), side="left")) - 1      # 最后一根日期 < D 的 K 线
        if i < 0:
            continue
        if prev is not None and i == prev:
            c = rows[-1]["close"]
            rows.append({"date": d, "open": c, "high": c, "low": c, "close": c, "volume": 0.0, **{k: rows[-1][k] for k in extra}})
            flat.append(True)
        else:
            if prev is not None and i - prev > 1:
                multi += 1
            b = src.iloc[i]
            rows.append({"date": d, **{k: b[k] for k in BAR_COLUMNS[1:] + extra}})
            flat.append(False)
        prev = i
    out = pd.DataFrame(rows, columns=BAR_COLUMNS + extra)
    run, hole, runs = 0, [], []                        # runs：连续平盘段 [起始行, 行数]
    for k, f in enumerate(flat):
        run = run + 1 if f else 0
        hole.append(int(run >= HOLE_MIN))
        if run == 1:
            runs.append([k, 0])
        if run:
            runs[-1][1] = run
    out["stale"], out["data_hole"] = [int(f) for f in flat], hole
    trailing = len(flat) - (max((k for k, f in enumerate(flat) if not f), default=-1) + 1)
    ends_at_tail = lambda r: r[0] + r[1] == len(flat)                                 # noqa: E731
    return out, {"calendar": "overseas_d_minus_1", "stale_days": sum(flat), "multi_bar_days": multi, "trailing_stale_days": trailing,
                 "last_bar_date": str(src["date"].iloc[prev].date()) if prev is not None else None,
                 "max_stale_run": max((n for k0, n in runs if not ends_at_tail([k0, n])), default=0),     # 中段最长连续平盘
                 "stale_runs": [{"first": str(out["date"].iloc[k0].date()), "last": str(out["date"].iloc[k0 + n - 1].date()),
                                 "rows": n, "trailing": ends_at_tail([k0, n]), "hole_rows": n - HOLE_MIN + 1}
                                for k0, n in runs if n >= HOLE_MIN],
                 "data_hole_rows": int(sum(hole))}


def bar_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """I-24：K 线级指标（形态状态、ATR20）在容器自己的 K 线上算。只用 t 及以前的行，算完再对齐不引入未来。"""
    if df.empty:
        return df.assign(state=pd.Series(dtype=object), atr20=pd.Series(dtype=float))
    return df.assign(state=form_states(df)["state"].to_numpy(), atr20=atr20(df).to_numpy())


def research_frame(con, cov: dict, cal: pd.DatetimeIndex, *, strict=False,
                   start: date | None = None, end: date | None = None) -> tuple[pd.DataFrame, dict]:
    """一个容器的研究序列：读取 → 借成交量（I-21）→ K 线级指标（I-24）→ 对齐 A 股日历（I-20）。数据包与每日任务共用，口径一致。
    海外容器的指标在其本地交易日的原生 K 线上算，长假内的高低点因此进入 hi20 / lo20 / ATR，平盘行不进指标（沿用上一根）；
    A 股容器先丢弃非日历行（那些行不是交易日）再算。"""
    overseas = cov.get("route_used") in OVERSEAS_ROUTES
    frame = None
    dropped = 0
    if strict:
        raw, rows = quality.input_rows(con, cov["series_code"], cov["series_adj"],
                                       [d.date().isoformat() for d in cal], start=start or cal[0].date(),
                                       end=end or cal[-1].date(), overseas=overseas)
        frame = _bar_frame(rows)
        dropped = len(raw) - len(rows) if not overseas else 0
    df, rep = load_series(con, cov["series_code"], cov["series_adj"], frame=frame, strict=strict)
    df, vsrc = borrow_volume(df, con, cov)
    rep["volume_source"] = vsrc
    if overseas:
        df, arep = align_to_calendar(bar_indicators(df), cal, True)
    else:
        df, arep = align_to_calendar(df, cal, False)
        df = bar_indicators(df)
    rep.update(arep)
    if strict and not overseas:
        rep["dropped_off_calendar"] = dropped
    rep["volume_zero_after_align"] = int((~(df["volume"] > 0)).sum()) if len(df) else 0
    return df, rep


def bench_open(con, code: str | None = None) -> pd.Series:
    """基准的原始开盘价（v1.1-e 基准窗口开盘到开盘用）。不用 load_series 补过的值：缺开盘的行记 NaN，由使用方退回收盘口径。"""
    raw = read_bars(con, code or BENCH_CODE, "raw")
    s = pd.Series(raw["open"].to_numpy(), index=raw["date"], dtype=float)
    return s.where(s > 0)


def container_panel(df: pd.DataFrame, bench: pd.Series, end: date, trading_days: pd.DatetimeIndex | None = None, *,
                    compute_indicators: bool = False) -> pd.DataFrame:
    """state / atr20 用 research_frame 带来的列（I-24）。缺这两列就报错，不静默在给定序列上重算——对齐后的海外序列上
    重算就是退回 P6a 口径（平盘进指标）。只有调用方明确给的是一条原生序列时才传 compute_indicators=True 就地算。
    rs_1m、z_month 用对齐后的收盘（横截面口径），不变。"""
    hole = df["data_hole"].to_numpy() if "data_hole" in df else None
    if compute_indicators:
        df = bar_indicators(df[BAR_COLUMNS])
    elif "state" not in df or "atr20" not in df:
        raise BuildError("缺 state / atr20：先经 research_frame 在原生 K 线上算（I-24），或对原生序列显式传 compute_indicators=True")
    if hole is None:
        if not compute_indicators:
            raise BuildError("缺 data_hole：先经 research_frame 对齐（I-25）")
        hole = np.zeros(len(df), dtype=int)                     # 原生序列没有平盘行，也就没有断档
    return pd.DataFrame({
        "date": df["date"], "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
        "state": df["state"], "rs_1m": rs_1m(df["close"], df["date"], bench), "atr20": df["atr20"],
        "z_month": z_month(df["close"], df["date"], end, trading_days=trading_days), "data_hole": hole,
    })


def _cell(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def write_panel_db(path: Path, panel: pd.DataFrame, bench: pd.DataFrame, meta: dict) -> None:
    """长表与基准写进一个新库（已有同名文件即替换）。日期存 YYYY-MM-DD，NaN 存 NULL。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.execute("PRAGMA journal_mode = DELETE")
        con.executescript(PANEL_SCHEMA)
        with con:
            con.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                            [("schema", PANEL_SCHEMA_VERSION)] + [(k, v if isinstance(v, str) else json.dumps(v)) for k, v in meta.items()])
            p = panel[PANEL_COLUMNS].assign(date=panel["date"].dt.strftime("%Y-%m-%d"), data_hole=panel["data_hole"].astype(int))
            con.executemany(f"INSERT INTO panel ({', '.join(PANEL_COLUMNS)}) VALUES ({', '.join('?' * len(PANEL_COLUMNS))})",
                            [tuple(_cell(v) for v in row) for row in p.itertuples(index=False, name=None)])
            b = bench.assign(date=bench["date"].dt.strftime("%Y-%m-%d"))[["date", "hs300", "hs300_open"]]
            con.executemany("INSERT INTO bench (date, hs300, hs300_open) VALUES (?, ?, ?)",
                            [tuple(_cell(v) for v in row) for row in b.itertuples(index=False, name=None)])
    finally:
        con.close()
    tmp.replace(path)


def build(package: Path, out: Path | None = None, *, start: date | None = None, log=print) -> Path:
    package = Path(package)
    problems = data_runner.verify(package)
    if problems:
        raise BuildError("研究数据包未通过复验：" + "; ".join(problems[:5]))
    con = DB.connect(package, readonly=True)
    try:
        con.execute("BEGIN")
        return _build(con, package, out, log, start=start)
    finally:
        con.close()


def _build(con, package: Path, out: Path | None, log, *, start: date | None = None) -> Path:
    info = data_runner.package_info(con)
    end = date.fromisoformat(info["end"])
    out = Path(out) if out else ROOT / "outputs" / f"panel-{end.isoformat()}.sqlite"
    covs = DB.read_coverage(con)

    readiness = quality.inspect(con, end, start=start)
    if not readiness["research_ready"]:
        log(json.dumps(readiness, ensure_ascii=False, indent=1))
        issues = readiness["issues"] + [f"H00300: {x}" for x in readiness["benchmark"]["issues"]]
        issues += [f"{tid}: {x}" for tid, c in readiness["containers"].items() for x in c["issues"]]
        raise BuildError("研究输入预检未通过（不补 OHLC、不自动剔除容器）：" + "; ".join(issues))
    trading_days = load_trading_days(con)
    cal = quality.window_days(trading_days, date.fromisoformat(readiness["start"]), end)
    # 基准独立读真实收盘；不经过策略的 OHLC 修整路径。
    bdf = read_bars(con, BENCH_CODE, "raw")
    bench = bdf.set_index("date")["close"].reindex(cal)

    pkg_sha = DB.sha256_file(package)
    frames, report = [], {"package": str(package), "package_sha256": pkg_sha, "package_content_sha256": info_content(package),
                          "end": end.isoformat(),
                          "source_db_sha256": info.get("source_db_sha256"), "git_commit_of_package": info.get("git_commit"),
                          "bench": {"code": BENCH_CODE, "first": str(bench.index.min().date()), "last": str(bench.index.max().date())},
                          "calendar": ({"days": len(trading_days), "first": str(trading_days[0].date()), "last": str(trading_days[-1].date())}
                                       if trading_days is not None else None),
                          "input_quality": readiness, "containers": {}, "skipped": {}}
    for c in covs:
        if c.get("status") not in ("retained", "flagged"):
            continue
        name = c["container"]
        if not c.get("series_adj") or not con.execute("SELECT 1 FROM bars WHERE code = ? AND adj = ? LIMIT 1",
                                                      (c["series_code"], c["series_adj"])).fetchone():
            raise BuildError(f"{name}: 无研究序列；不自动剔除容器")
        df, rep = research_frame(con, c, cal, strict=True, start=date.fromisoformat(readiness["start"]), end=end)
        if df.empty:
            raise BuildError(f"{name}: 对齐 A 股日历后没有行；不自动剔除容器")
        p = container_panel(df, bench, end, trading_days)
        p.insert(1, "container", name)
        frames.append(p)
        rep.update(series_code=c["series_code"], series_adj=c["series_adj"], route=c["route_used"], price_only=c["price_only"],
                   first=str(df["date"].min().date()), last=str(df["date"].max().date()), aligned_rows=len(df),
                   states={k: int(v) for k, v in p.loc[df["stale"].to_numpy() == 0, "state"].value_counts().items()},   # 只数非平盘行
                   z_month_values=int(p["z_month"].notna().sum()))
        report["containers"][name] = rep
        flags = {"补开高低": rep["ohl_filled_from_close"], "扩高低": rep["hl_clamped"], "原始无成交量": rep["volume_missing_or_zero"],
                 "缺收盘丢弃": rep["dropped_missing_close"], "重复日期": rep["dropped_duplicate_dates"],
                 "不在 A 股日历丢弃": rep.get("dropped_off_calendar", 0), "日历内缺日": rep.get("missing_on_calendar", 0),
                 "平盘": rep.get("stale_days", 0),
                 "长假并入最后一根": rep.get("multi_bar_days", 0), "数据断档（V1 不做决策）": rep.get("data_hole_rows", 0)}
        log(f"  ok  {name}: {rep['aligned_rows']} 行 {rep['first']}→{rep['last']}；成交量 {rep['volume_source']}"
            + "".join(f"；{k} {v} 行" for k, v in flags.items() if v)
            + (f"；⚠ 末尾连续平盘 {rep['trailing_stale_days']} 行（序列可能停更）" if rep.get("trailing_stale_days", 0) > 3 else "")
            + "".join(f"；⚠ 断档 {r['first']}→{r['last']} {r['rows']} 行" for r in rep.get("stale_runs", [])))
    if not frames:
        raise BuildError("没有任何容器有研究序列")
    panel = pd.concat(frames, ignore_index=True).sort_values(["date", "container"]).reset_index(drop=True)
    bench_df = pd.DataFrame({"date": bench.index, "hs300": bench.to_numpy(),
                             "hs300_open": bench_open(con).reindex(bench.index).to_numpy()})
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    window_meta = {k: json.dumps(readiness[k], ensure_ascii=False, sort_keys=True)
                   for k in ("requested_window", "trusted_calendar_range", "effective_window")}
    write_panel_db(out, panel, bench_df, {"end": end.isoformat(), "package_content_sha256": info_content(package), **window_meta})
    report["created_at"] = created                                  # 时刻只进报告，面板库由数据包与声明窗口决定
    report["panel_db"], report["panel_db_sha256"] = out.name, DB.sha256_file(out)
    report["panel_content_sha256"] = panel_content_sha256(out)
    report_path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"  面板 {len(panel)} 行、{len(frames)} 个容器 → {out}")
    return out


def info_content(package: Path) -> str | None:
    """数据包 MANIFEST.json 里的 content_sha256（verify 已核对过它与包内容一致）。"""
    man = data_runner.manifest_path(package)
    return json.loads(man.read_text(encoding="utf-8")).get("content_sha256") if man.exists() else None


def panel_content_sha256(panel_db: Path) -> str:
    """面板库内容的规范化哈希（与 SQLite 版本、文件布局无关）；build-report 与 V1 的 OOS 锁都记它。"""
    from src.research.prereg_v1.panel import content_sha256
    return content_sha256(panel_db)


def report_path(panel_db: Path) -> Path:
    """panel-D.sqlite → panel-D.build-report.json（run check 从这里读各容器的 stale_runs）。"""
    return Path(panel_db).with_name(Path(panel_db).stem + ".build-report.json")


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
