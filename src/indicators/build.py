"""研究数据包 → V1 长表（implementation-notes §B）。

    python -m src.indicators build --package outputs/research-package-2026-09-30/ [--out outputs/panel-2026-09-30/]

输出 panel.csv（date, container, open, high, low, close, state, rs_1m, atr20, z_month）、bench.csv（date, hs300 = H00300 收盘,
hs300_open = 原始开盘，缺则空；每日任务的基准窗口用）
和 build-report.json（每个容器的数据处理与缺陷计数）。全收益指数借价格版本的成交量（I-21），K 线级指标（state、atr20）在容器
原生序列上算（I-24），再对齐到 A 股日历（I-20）；rs_1m、z_month 在对齐后的收盘上算。之后跑
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
from src.data import store
from .calendar import CALENDAR, load_trading_days
from .metrics import atr20, rs_1m, z_month
from .states import form_states

BENCH_CODE = "H00300"          # I-18：沪深300 全收益，不用价格指数 000300 顶替
OVERSEAS_ROUTES = {"yahoo", "stooq", "eia"}      # I-20：本地日期晚于 A 股收盘的路由，取 D−1
VOLUME_BORROW_SHARE = 0.5      # I-21：研究序列缺成交量的行超过一半就借价格版本
PANEL_COLUMNS = ["date", "container", "open", "high", "low", "close", "state", "rs_1m", "atr20", "z_month"]
BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
ROOT = Path(__file__).resolve().parents[2]


class BuildError(RuntimeError):
    pass


def load_series(path: Path) -> tuple[pd.DataFrame, dict]:
    """读 raw 序列并做最小修整，修了什么都计数进报告：
    - 开 / 高 / 低缺失或非正时用收盘补（EIA 布伦特只有收盘；ATR 因此退化为收盘到收盘的波幅）；
    - 高 / 低没有包住开收时，把高低价扩到包住开收（build_hfq.py 对腾讯两位小数高低价的同一处理）；
    - 收盘缺失的行丢弃；收盘非正直接报错。"""
    df = pd.read_csv(path, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    bad = df["close"].notna() & ~(df["close"] > 0)
    if bad.any():          # P1 从不请求减法前复权：出现非正收盘就是数据坏了，不静默丢掉（也让下游的负价防线有意义）
        raise BuildError(f"{path.name}: {int(bad.sum())} 行收盘非正（首个 {df.loc[bad, 'date'].iloc[0].date()}）")
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


def borrow_volume(df: pd.DataFrame, raw_dir: Path, cov: dict) -> tuple[pd.DataFrame, str]:
    """I-21：研究序列缺成交量的行超过一半时，按日期换成同一指数价格版本（coverage.code 的原始文件）的成交量。
    价格版本成份与交易日相同，成交量本是同一个数；放量条件是比值，单位无关。价格版本也没有成交量则保持原样。
    返回 (df, volume_source ∈ self / price_version / none)。"""
    if df.empty or (~(df["volume"] > 0)).mean() <= VOLUME_BORROW_SHARE:
        return df, "self"
    code = cov.get("code") or ""
    if not code or cov.get("series_code") == code:           # 研究序列就是价格版本本身（或研究 = 执行的后复权 ETF）
        return df, "none"
    pf = Path(raw_dir) / store.file_name(code, "csi")          # 价格版本不走后复权路由，文件名即 <code>.csv
    if not pf.exists():
        return df, "none"
    pv = pd.read_csv(pf, dtype={"date": str})
    vol = pd.Series(pd.to_numeric(pv.get("volume"), errors="coerce").to_numpy(), index=pd.to_datetime(pv["date"]))
    vol = vol[~vol.index.duplicated(keep="last")]
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
    df 里 K 线以外的列（I-24：原生序列上算好的指标）随 K 线一起带到 D；平盘行沿用上一行的值。"""
    if not overseas:
        on = df["date"].isin(cal)
        kept = df[on].reset_index(drop=True)
        span = cal[(cal >= kept["date"].min()) & (cal <= kept["date"].max())] if len(kept) else cal[:0]
        return kept, {"calendar": "a_share", "dropped_off_calendar": int((~on).sum()),
                      "missing_on_calendar": int((~span.isin(kept["date"])).sum())}
    src = df.sort_values("date").reset_index(drop=True)
    dates = src["date"].to_numpy()
    extra = [c for c in src.columns if c not in BAR_COLUMNS]
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
    trailing = len(flat) - (max((k for k, f in enumerate(flat) if not f), default=-1) + 1)
    return out, {"calendar": "overseas_d_minus_1", "stale_days": sum(flat), "multi_bar_days": multi, "trailing_stale_days": trailing,
                 "last_bar_date": str(src["date"].iloc[prev].date()) if prev is not None else None}


def bar_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """I-24：K 线级指标（形态状态、ATR20）在容器自己的 K 线上算。只用 t 及以前的行，算完再对齐不引入未来。"""
    if df.empty:
        return df.assign(state=pd.Series(dtype=object), atr20=pd.Series(dtype=float))
    return df.assign(state=form_states(df)["state"].to_numpy(), atr20=atr20(df).to_numpy())


def research_frame(raw_dir: Path, cov: dict, cal: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    """一个容器的研究序列：读取 → 借成交量（I-21）→ K 线级指标（I-24）→ 对齐 A 股日历（I-20）。数据包与每日任务共用，口径一致。
    海外容器的指标在其本地交易日的原生 K 线上算，长假内的高低点因此进入 hi20 / lo20 / ATR，平盘行不进指标（沿用上一根）；
    A 股容器先丢弃非日历行（那些行不是交易日）再算。"""
    df, rep = load_series(Path(raw_dir) / cov["series_file"])
    df, vsrc = borrow_volume(df, raw_dir, cov)
    rep["volume_source"] = vsrc
    overseas = cov.get("route_used") in OVERSEAS_ROUTES
    if overseas:
        df, arep = align_to_calendar(bar_indicators(df), cal, True)
    else:
        df, arep = align_to_calendar(df, cal, False)
        df = bar_indicators(df)
    rep.update(arep)
    rep["volume_zero_after_align"] = int((~(df["volume"] > 0)).sum()) if len(df) else 0
    return df, rep


def bench_open(path: Path) -> pd.Series:
    """基准的原始开盘价（v1.1-e 基准窗口开盘到开盘用）。不用 load_series 补过的值：缺开盘的行记 NaN，由使用方退回收盘口径。"""
    raw = pd.read_csv(path, dtype={"date": str})
    s = pd.Series(pd.to_numeric(raw.get("open"), errors="coerce").to_numpy(), index=pd.to_datetime(raw["date"]), dtype=float)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.where(s > 0)


def container_panel(df: pd.DataFrame, bench: pd.Series, end: date, trading_days: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """state / atr20 用 research_frame 带来的列（I-24）；调用方直接给一条原生序列（没有这两列）时就地算。
    rs_1m、z_month 用对齐后的收盘（横截面口径），不变。"""
    if "state" not in df or "atr20" not in df:
        df = bar_indicators(df)
    return pd.DataFrame({
        "date": df["date"], "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
        "state": df["state"], "rs_1m": rs_1m(df["close"], df["date"], bench), "atr20": df["atr20"],
        "z_month": z_month(df["close"], df["date"], end, trading_days=trading_days),
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
    cal = bench.index[bench.index <= pd.Timestamp(end)]
    cal_file = package / "calendar" / CALENDAR.name
    try:
        trading_days = load_trading_days(cal_file)
    except ValueError as e:
        raise BuildError(f"数据包里的交易日历不可用：{e}") from e

    frames, report = [], {"package": str(package), "end": end.isoformat(), "manifest_sha256": _sha256(package / "MANIFEST.sha256"),
                          "bench": {"code": BENCH_CODE, "first": str(bench.index.min().date()), "last": str(bench.index.max().date())},
                          "calendar_file": _sha256(cal_file) if trading_days is not None else None,
                          "containers": {}, "skipped": {}}
    panel_rows = cov[cov["status"].isin(["retained", "flagged"])]
    for _, c in panel_rows.iterrows():
        name = c["container"]
        if not c["series_file"] or not (package / "raw" / c["series_file"]).exists():
            report["skipped"][name] = c["error"] or "无研究序列"
            log(f"  --  {name}: 跳过（{report['skipped'][name][:80]}）")
            continue
        df, rep = research_frame(package / "raw", dict(c), cal)
        if df.empty:
            report["skipped"][name] = "对齐 A 股日历后没有行"
            log(f"  --  {name}: 跳过（对齐 A 股日历后没有行）")
            continue
        p = container_panel(df, bench, end, trading_days)
        p.insert(1, "container", name)
        frames.append(p)
        rep.update(series_file=c["series_file"], route=c["route_used"], price_only=c["price_only"],
                   first=str(df["date"].min().date()), last=str(df["date"].max().date()), aligned_rows=len(df),
                   states={k: int(v) for k, v in p["state"].value_counts().items()},
                   z_month_values=int(p["z_month"].notna().sum()))
        report["containers"][name] = rep
        flags = {"补开高低": rep["ohl_filled_from_close"], "扩高低": rep["hl_clamped"], "原始无成交量": rep["volume_missing_or_zero"],
                 "缺收盘丢弃": rep["dropped_missing_close"], "重复日期": rep["dropped_duplicate_dates"],
                 "不在 A 股日历丢弃": rep.get("dropped_off_calendar", 0), "日历内缺日": rep.get("missing_on_calendar", 0),
                 "平盘": rep.get("stale_days", 0),
                 "长假并入最后一根": rep.get("multi_bar_days", 0)}
        log(f"  ok  {name}: {rep['aligned_rows']} 行 {rep['first']}→{rep['last']}；成交量 {rep['volume_source']}"
            + "".join(f"；{k} {v} 行" for k, v in flags.items() if v)
            + (f"；⚠ 末尾连续平盘 {rep['trailing_stale_days']} 行（序列可能停更）" if rep.get("trailing_stale_days", 0) > 3 else ""))
    if not frames:
        raise BuildError("没有任何容器有研究序列")
    panel = pd.concat(frames, ignore_index=True).sort_values(["date", "container"]).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    panel[PANEL_COLUMNS].to_csv(out / "panel.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame({"date": bench.index, "hs300": bench.to_numpy(),
                  "hs300_open": bench_open(bench_path).reindex(bench.index).to_numpy()}).to_csv(out / "bench.csv", index=False,
                                                                                                date_format="%Y-%m-%d")
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
