"""假网络：按请求参数从合成序列里切出响应，格式与 fixtures 一致。没登记的代码一律抛 FetchError（模拟 403 / 404）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from src.data import http


def bdays(start: str, end: str) -> list[str]:
    d, e, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def series(start: str, end: str, base: float = 100.0) -> list[tuple[str, float]]:
    return [(d, round(base + i * 0.1, 4)) for i, d in enumerate(bdays(start, end))]


class FakeNet:
    def __init__(self):
        self.csi, self.em, self.tencent, self.yahoo, self.stooq, self.eia = {}, {}, {}, {}, {}, {}
        self.calls: list[str] = []
        self.fail_after: dict[str, int] = {}     # key → 第 n 次请求起失败（测分段中途断）

    # 登记：key → (name, [(date, close)])
    def add(self, kind: str, key: str, name: str | None, start: str, end: str, base: float = 100.0):
        getattr(self, kind)[key] = (name, series(start, end, base))
        return self

    def _bump(self, key: str):
        n = sum(1 for c in self.calls if c == key)
        self.calls.append(key)
        if key in self.fail_after and n >= self.fail_after[key]:
            raise http.FetchError(f"URLError: simulated drop  ← {key}")

    def get(self, url, params=None, **kw) -> bytes:
        u = urlparse(url)
        q = {k: str(v) for k, v in (params or {}).items()}
        q.update({k: v[0] for k, v in parse_qs(u.query).items()})
        host = u.netloc
        if host == "www.csindex.com.cn":
            key = q["indexCode"]
            self._bump(f"csi:{key}")
            if key not in self.csi:
                raise http.FetchError(f"HTTPError: 404  ← {url}")
            name, rows = self.csi[key]
            b, e = _iso(q["startDate"]), _iso(q["endDate"])
            data = [{"tradeDate": d.replace("-", ""), "indexNameCnAll": name, "open": c, "high": c + 1, "low": c - 1, "close": c,
                     "tradingVol": 1.0, "tradingValue": 2.0} for d, c in rows if b <= d <= e]
            return json.dumps({"code": "200", "msg": "Success", "success": True, "data": data[::-1]}, ensure_ascii=False).encode()
        if host == "push2his.eastmoney.com":
            key = f"{q['secid']}:{q['fqt']}"
            self._bump(f"em:{key}")
            if key not in self.em:
                raise http.FetchError(f"URLError: Tunnel connection failed: 403 Forbidden  ← {url}")
            name, rows = self.em[key]
            b, e = _iso(q["beg"]), _iso(q["end"])
            kl = [f"{d},{c},{c},{c + 0.01},{c - 0.01},100,1000.0,0,0,0,0" for d, c in rows if b <= d <= e]
            return json.dumps({"rc": 0, "data": {"name": name, "klines": kl} if kl else None}, ensure_ascii=False).encode()
        if host == "web.ifzq.gtimg.cn":
            sym, _, b, e, *_ = q["param"].split(",")
            self._bump(f"tencent:{sym}")
            if sym not in self.tencent:
                raise http.FetchError(f"HTTPError: 404  ← {url}")
            name, rows = self.tencent[sym]
            day = [[d, str(c), str(c), str(c + 0.01), str(c - 0.01), "100"] for d, c in rows if b <= d <= e]
            return json.dumps({"code": 0, "data": {sym: {"day": day, "qt": {sym: ["1", name, sym[2:]]}}}}, ensure_ascii=False).encode()
        if host == "query1.finance.yahoo.com":
            sym = u.path.rsplit("/", 1)[-1]
            self._bump(f"yahoo:{sym}")
            if sym not in self.yahoo:
                return json.dumps({"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}).encode()
            name, rows = self.yahoo[sym]
            p1, p2 = int(q["period1"]), int(q["period2"])
            sel = [(int(datetime.fromisoformat(d).replace(hour=14, tzinfo=timezone.utc).timestamp()), c) for d, c in rows]
            sel = [(t, c) for t, c in sel if p1 <= t < p2]
            return json.dumps({"chart": {"error": None, "result": [{"meta": {"gmtoffset": -14400, "longName": name},
                               "timestamp": [t for t, _ in sel], "indicators": {"quote": [{
                                   "open": [c for _, c in sel], "high": [c + 1 for _, c in sel], "low": [c - 1 for _, c in sel],
                                   "close": [c for _, c in sel], "volume": [0 for _ in sel]}]}}]}}).encode()
        if host == "stooq.com":
            sym = q["s"]
            self._bump(f"stooq:{sym}")
            if sym not in self.stooq:
                return b"No data"
            _, rows = self.stooq[sym]
            b, e = _iso(q["d1"]), _iso(q["d2"])
            return ("Date,Open,High,Low,Close,Volume\n" + "".join(f"{d},{c},{c + 1},{c - 1},{c},0\n" for d, c in rows if b <= d <= e)).encode()
        if host == "api.eia.gov":
            sid = u.path.rsplit("/", 1)[-1]
            self._bump(f"eia:{sid}")
            if sid not in self.eia:
                raise http.FetchError(f"HTTPError: 404  ← {url}")
            name, rows = self.eia[sid]
            sel = [(d, c) for d, c in rows if q["start"] <= d <= q["end"]]
            off, n = int(q["offset"]), int(q["length"])
            data = [{"period": d, "value": c, "series-description": name} for d, c in sel[off:off + n]]
            return json.dumps({"response": {"total": str(len(sel)), "data": data}}).encode()
        raise http.FetchError(f"unknown host {host}")


def _iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
