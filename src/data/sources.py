"""各行情源的抓取与解析。每个 fetch_* 返回 Fetched(rows, name)：
rows 是按日期升序的 {date, open, high, low, close, volume, amount}，name 是源返回的证券 / 指数名称（没有则 None）。

分段、UA、东财 120 天一段、Yahoo → stooq 依次退的做法抄自 serenity_quant_research（physical-first）
api/app/ingest/quotes.py；中证、腾讯、EIA 按 intake §5 与 replan §3 P1 的接口说明写。
成交量 / 成交额保留各源原始单位，不做换算（东财、腾讯成交量是「手」；中证的量额单位未核实）。
fixtures 里的响应按接口格式构造，首次在能出网的机器上 `probe --record` 后应以真实录制替换。
"""
from __future__ import annotations

import csv
import io
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import http

CSI_PERF = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
STOOQ_CSV = "https://stooq.com/q/d/l/"
EIA_SERIES = "https://api.eia.gov/v2/seriesid/{series}"

EM_CHUNK_DAYS = 120         # 东财一次只要 4 个月，长窗口在服务器上会断连
TENCENT_CHUNK_DAYS = 500    # 腾讯单次上限 400 行；500 个日历日约 340 个交易日
EIA_PAGE = 5000             # EIA API v2 单次最多 5000 行
PAUSE = {"csi": 0.3, "eastmoney": 1.5, "tencent": 0.3, "eia": 0.3}   # 段间歇（秒）


@dataclass
class Fetched:
    rows: list[dict] = field(default_factory=list)
    name: str | None = None
    dropped: int = 0            # 因未收盘被丢弃的行数（runner 填）
    warnings: list[str] = field(default_factory=list)


def _f(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None       # NaN
    except (TypeError, ValueError):
        return None


def _row(d: str, o, h, l, c, vol=None, amt=None) -> dict | None:
    close = _f(c)
    if close is None:
        return None
    return {"date": d, "open": _f(o), "high": _f(h), "low": _f(l), "close": close, "volume": _f(vol), "amount": _f(amt)}


def _finish(rows: list[dict], start: date, end: date) -> list[dict]:
    """按日期去重（后到的覆盖先到的）、裁到 [start, end]、升序。"""
    lo, hi = start.isoformat(), end.isoformat()
    by = {r["date"]: r for r in rows if r and lo <= r["date"] <= hi}
    return [by[d] for d in sorted(by)]


def _segments(start: date, end: date, days: int):
    beg = start
    while beg <= end:
        stop = min(beg + timedelta(days=days - 1), end)
        yield beg, stop
        beg = stop + timedelta(days=1)


def _hole(what: str, b: date, e: date, have_rows: bool, is_last: bool) -> None:
    """已经拿到过数据之后又出现空段（且不是最后一段）= 序列中间有洞或已停更：整条失败，不留缺口。
    上市 / 基日之前的空段、最后一段为空（节假日）都正常。"""
    if have_rows and not is_last:
        raise http.FetchError(f"{what} {b}~{e}: 数据中间出现空段（中断或停更），整条不用")


def _year_segments(start: date, end: date):
    for y in range(start.year, end.year + 1):
        yield max(start, date(y, 1, 1)), min(end, date(y, 12, 31))


# ------------------------------------------------------------------ 中证指数官网
def fetch_csindex(code: str, start: date, end: date) -> Fetched:
    """`perf/index-perf?indexCode=&startDate=&endDate=`，按年分段。任一段失败即整条失败（不留缺口）。"""
    rows, name, biz_err = [], None, []
    segs = list(_year_segments(start, end))
    for i, (b, e) in enumerate(segs):
        d = http.get_json(CSI_PERF, {"indexCode": code, "startDate": b.strftime("%Y%m%d"), "endDate": e.strftime("%Y%m%d")},
                          headers={"Referer": "https://www.csindex.com.cn/"})
        ok = isinstance(d, dict) and str(d.get("code")) == "200"
        if not ok:
            why = (f"code={d.get('code')} msg={d.get('msg')}" if isinstance(d, dict) else str(d)[:60])
            if rows:                   # 有数据之后再出业务错误：真错
                raise http.FetchError(f"csindex {code} {b}~{e}: {why}")
            biz_err.append(f"{b.year}: {why}")   # 基日之前可能返回业务错误而非空数据——先记下，不静默吞掉
        data = (d.get("data") or []) if ok else []
        if not data:
            _hole(f"csindex {code}", b, e, bool(rows), i + 1 == len(segs))
        for r in data:
            td = str(r.get("tradeDate") or "")
            if len(td) != 8:
                continue
            name = name or " / ".join(x for x in (r.get("indexNameCnAll") or r.get("indexNameCn"),
                                                  r.get("indexNameEnAll") or r.get("indexNameEn")) if x) or None
            rows.append(_row(f"{td[:4]}-{td[4:6]}-{td[6:]}", r.get("open"), r.get("high"), r.get("low"), r.get("close"),
                             r.get("tradingVol"), r.get("tradingValue")))
        if i + 1 < len(segs):
            time.sleep(PAUSE["csi"])
    if not rows and biz_err:
        raise http.FetchError(f"csindex {code}: 各段均无数据，业务错误 {len(biz_err)} 段，最后一段 {biz_err[-1]}")
    warn = [f"起点前 {len(biz_err)} 段返回业务错误（{biz_err[-1]}），first_date 可能被截短"] if rows and biz_err else []
    return Fetched(_finish(rows, start, end), name, warnings=warn)


# ------------------------------------------------------------------ 东方财富 K 线
def fetch_eastmoney(secid: str, start: date, end: date, fqt: int = 0) -> Fetched:
    """fqt：0 不复权、2 后复权。按 120 天分段；上市前的段为空属正常，某段请求失败则整条失败。"""
    rows, name = [], None
    segs = list(_segments(start, end, EM_CHUNK_DAYS))
    for i, (b, e) in enumerate(segs):
        d = http.get_json(EM_KLINE, {
            "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101, "fqt": fqt, "beg": b.strftime("%Y%m%d"), "end": e.strftime("%Y%m%d"), "lmt": 10000,
        }, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=12)
        if (d or {}).get("rc", 0) != 0:          # 上市前东财返回 rc=0 + 空数据；rc≠0 一律是错误
            raise http.FetchError(f"eastmoney {secid} {b}~{e}: rc={d.get('rc')}")
        data = (d or {}).get("data") or {}
        name = name or data.get("name")
        if not data.get("klines"):
            _hole(f"eastmoney {secid}", b, e, bool(rows), i + 1 == len(segs))
        for line in data.get("klines") or []:
            p = line.split(",")
            if len(p) < 7:
                continue
            # 日期,开,收,高,低,成交量(手),成交额,…
            rows.append(_row(p[0], p[1], p[3], p[4], p[2], p[5], p[6]))
        if i + 1 < len(segs):
            time.sleep(PAUSE["eastmoney"])
    return Fetched(_finish(rows, start, end), name)


# ------------------------------------------------------------------ 腾讯（只用不复权）
def fetch_tencent(sym: str, start: date, end: date) -> Fetched:
    """`fqkline/get?param=<sym>,day,<start>,<end>,400,`（复权参数留空 = 不复权）。
    腾讯的 qfq 是减法复权（intake §4.2 陷阱 3），这里从不请求 qfq。返回行是 [日期, 开, 收, 高, 低, 量]。"""
    rows, name = [], None
    segs = list(_segments(start, end, TENCENT_CHUNK_DAYS))
    for i, (b, e) in enumerate(segs):
        d = http.get_json(TENCENT_KLINE, {"param": f"{sym},day,{b.isoformat()},{e.isoformat()},400,"})
        if not isinstance(d, dict) or d.get("code") not in (0, "0"):
            raise http.FetchError(f"tencent {sym} {b}~{e}: {str(d)[:80]}")
        node = ((d.get("data") or {}).get(sym)) or {}
        if not isinstance(node, dict):
            node = {}
        qt = (node.get("qt") or {}).get(sym)
        if isinstance(qt, list) and len(qt) > 1:
            name = name or qt[1]
        if not node.get("day"):
            _hole(f"tencent {sym}", b, e, bool(rows), i + 1 == len(segs))
        for p in node.get("day") or []:
            if len(p) >= 6:
                rows.append(_row(p[0], p[1], p[3], p[4], p[2], p[5]))
        if i + 1 < len(segs):
            time.sleep(PAUSE["tencent"])
    return Fetched(_finish(rows, start, end), name)


# ------------------------------------------------------------------ Yahoo / stooq
def _zone(name: str | None):
    try:
        return ZoneInfo(name) if name else None
    except Exception:  # noqa: BLE001 — 未知时区名
        return None


def fetch_yahoo(sym: str, start: date, end: date) -> Fetched:
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400
    d = http.get_json(YAHOO_CHART.format(sym=sym), {"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"})
    res = ((d or {}).get("chart") or {}).get("result") or []
    if not res:
        err = ((d or {}).get("chart") or {}).get("error")
        raise http.FetchError(f"yahoo {sym}: {err or 'no result'}")
    r = res[0]
    meta = r.get("meta") or {}
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    tz = _zone(meta.get("exchangeTimezoneName"))
    off = meta.get("gmtoffset") or 0
    col = lambda k: q.get(k) or [None] * len(ts)   # noqa: E731
    o, h, l, c, v = col("open"), col("high"), col("low"), col("close"), col("volume")
    rows = []
    for i, t in enumerate(ts):
        # 按交易所时区逐个换算（夏令时前后偏移不同）；拿不到时区名才退回当前 gmtoffset
        dd = (datetime.fromtimestamp(t, tz) if tz else datetime.fromtimestamp(t, timezone.utc) + timedelta(seconds=off)).date().isoformat()
        rows.append(_row(dd, o[i], h[i], l[i], c[i], v[i]))    # 指数用原始收盘；不取 adjclose
    return Fetched(_finish(rows, start, end), meta.get("longName") or meta.get("shortName"))


def fetch_stooq(sym: str, start: date, end: date) -> Fetched:
    raw = http.get(STOOQ_CSV, {"s": sym, "i": "d", "d1": start.strftime("%Y%m%d"), "d2": end.strftime("%Y%m%d")})
    text = raw.decode("utf-8", "ignore")
    if "Date" not in text[:200]:
        raise http.FetchError(f"stooq {sym}: {text[:80]!r}")
    rows = [_row(r["Date"], r.get("Open"), r.get("High"), r.get("Low"), r.get("Close"), r.get("Volume"))
            for r in csv.DictReader(io.StringIO(text))]
    return Fetched(_finish(rows, start, end), None)


# ------------------------------------------------------------------ EIA（布伦特现货 RBRTE）
def fetch_eia(series: str, start: date, end: date) -> Fetched:
    """EIA API v2 的 seriesid 兼容入口（如 PET.RBRTE.D），需环境变量 EIA_API_KEY；只有收盘值，无开高低。"""
    key = os.environ.get("EIA_API_KEY")
    if not key:
        raise http.FetchError("EIA_API_KEY 未设置（EIA API v2 需要免费 key）")
    rows, offset, total, name = [], 0, None, None
    while total is None or offset < total:
        d = http.get_json(EIA_SERIES.format(series=series), {
            "api_key": key, "start": start.isoformat(), "end": end.isoformat(),
            "sort[0][column]": "period", "sort[0][direction]": "asc", "offset": offset, "length": EIA_PAGE})
        resp = (d or {}).get("response") or {}
        if "data" not in resp:
            raise http.FetchError(f"eia {series}: {str((d or {}).get('error') or d)[:120]}")
        data = resp.get("data") or []
        total = int(resp.get("total") or 0)
        for r in data:
            name = name or r.get("series-description")
            rows.append(_row(str(r.get("period"))[:10], None, None, None, r.get("value")))
        if not data:
            break
        offset += len(data)
        if offset < total:
            time.sleep(PAUSE["eia"])
    return Fetched(_finish(rows, start, end), name)
