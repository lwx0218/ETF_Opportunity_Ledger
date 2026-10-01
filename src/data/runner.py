"""probe / backfill / update / calendar / package / verify / compare，读写 data/market.sqlite（replan §11）。

probe     对 universe 每一行试路由，coverage 写进库（数据源可用性的最小验证，也是 R0「核实」的最终形式）。
backfill  全量拉进 bars 表，同时写 coverage。
update    按库里每条序列已有的来源增量拉取，往回多拉 OVERLAP_DAYS 天覆盖修正；每条序列的结果记 update_results。
calendar  校验 astra 生成的交易日清单，写进 calendar 表。
package   从库复制一份截到 end 的只读库 outputs/research-package-<end>.sqlite（+ 同名 .MANIFEST.json 记 sha256）；只读源库。
probe / backfill / update / calendar 每次在 runs 记一行（起止、end、参数、git commit、universe seed 的 sha256），请求记录进 requests。
拿不到的容器只记一行 error 跳过，不阻塞其他容器（replan §6.4）。
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db as DB
from . import http, store
from . import universe as U

ROOT = U.ROOT
PKG_ROOT = ROOT / "outputs"
DEFAULT_START = date(2000, 1, 1)
PROBE_WINDOW_DAYS = 45       # 全收益候选与执行 ETF 只看最近一段：确认存在与名称
OVERLAP_DAYS = 10
MAX_GAP_DAYS = 20            # 超过即在 notes 提示（春节长假约 10 天）
INDEX_ROUTES = {"csi", "eastmoney_index", "yahoo"}     # universe 路由里属于价格指数的：无全收益版本即 price_only
BEIJING = timezone(timedelta(hours=8))                  # 北京不用夏令时，固定偏移即可
try:
    NEW_YORK = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 — 缺 tzdata 的精简镜像：按 UTC−5（冬令时）算，收盘判定只会更保守
    NEW_YORK = timezone(timedelta(hours=-5))
A_SHARE_ROUTES = {"csi", "eastmoney_index", "tencent_index", "eastmoney_etf_hfq", "eastmoney_etf", "tencent_etf"}
STRICT_ROUTES = {"eastmoney_etf_hfq"}   # 后复权：重叠区被改写 = 复权基准变了，不能拼接
NOT_ATTEMPTED = {"518880": "上海金 Au99.99 未尝试：固定源与 replan 均未给出接口"}

COVERAGE_COLUMNS = DB.COVERAGE_COLUMNS
_TR_MARK = re.compile(r"全收益|财富|total\s*return|\bN?TR\b", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def last_complete(route: str, now: datetime | None = None) -> date:
    """该路由最近一根已收盘日线的日期：A 股按北京时间 15:30，海外按纽约时间 17:00（亚洲海外指数更早收盘，按纽约算只会更保守）。
    抓取时比它新的 K 线是盘中实时值，一律丢弃，不进库、更不进数据包。"""
    now = now or _utcnow()
    if route in A_SHARE_ROUTES:
        t, cut = now.astimezone(BEIJING), time(15, 30)
    else:
        t, cut = now.astimezone(NEW_YORK), time(17, 0)
    return t.date() if t.time() >= cut else t.date() - timedelta(days=1)


def price_only_flag(row: dict) -> str:
    """价格指数 → True；商品（布伦特现货 / 期货，无分红也无展期收益）→ n/a，不按指数的每年 1% 规则处理。"""
    if row.get("research_route") == "eia_or_yahoo":
        return "n/a"
    return str(row.get("research_route") in INDEX_ROUTES)


def is_tr_name(name: str | None) -> bool:
    return bool(name and _TR_MARK.search(name))


def fetch_chain(chain: list[str], code: str, start: date, end: date):
    """依次试路由；返回 (route, Fetched, 失败原因列表)，全失败时前两项为 None。"""
    errors: list[str] = []
    for route in chain:
        fn = U.route_fn(route, code)
        if fn is None:
            errors.append(f"{route}: 无 {code} 的代码映射")
            continue
        try:
            got = fn(start, end)
        except Exception as e:  # noqa: BLE001 — 记一行，退下一条路
            errors.append(f"{route}: {str(e)[:200]}")
            continue
        cutoff = last_complete(route).isoformat()
        n0 = len(got.rows)
        got.rows = [r for r in got.rows if r["date"] <= cutoff]
        got.dropped = n0 - len(got.rows)
        if got.rows:
            return route, got, errors
        errors.append(f"{route}: 0 行")
    return None, None, errors


def detect_tr(row: dict, route: str, end: date) -> tuple[str | None, list[str]]:
    """逐个试 tr_code_candidates：第一个有数据且名称含「全收益 / 财富 / Total Return」的即采用。"""
    notes = []
    for cand in U.tr_candidates(row):
        r, got, errs = fetch_chain([route], cand, end - timedelta(days=PROBE_WINDOW_DAYS), end)
        if got is None:
            notes.append(f"全收益候选 {cand} 不可得（{'; '.join(errs)[:160]}）")
        elif is_tr_name(got.name):
            return cand, notes
        else:
            notes.append(f"全收益候选 {cand} 名称「{got.name}」无全收益标记，未采用")
    return None, notes


def max_gap(rows: list[dict]) -> tuple[int, str | None, str | None]:
    worst = (0, None, None)
    for a, b in zip(rows, rows[1:]):
        g = (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days
        if g > worst[0]:
            worst = (g, a["date"], b["date"])
    return worst


def gap_note(rows: list[dict], what: str = "") -> str | None:
    g, a, b = max_gap(rows)
    return f"{what}最大间隔 {g} 天（{a}→{b}）" if g > MAX_GAP_DAYS else None


def _missing(rows: list[dict], cols) -> int:
    return sum(1 for r in rows if not all((r.get(c) or 0) > 0 for c in cols))


def collect(row: dict, start: date, end: date, *, full: bool, exec_start: date | None = None) -> tuple[dict, list[tuple[str, str, list[dict]]]]:
    """一个容器 → (coverage 行, 要落库的序列 [(code, route, rows)])。
    full=False（probe）：执行 ETF 只查最近一段，价格序列在已有全收益时不再拉；full=True（backfill）：全部全量。"""
    cov = {k: "" for k in COVERAGE_COLUMNS}
    cov.update(container=row["theme"], code=row.get("research_index_code", ""), theme_id=row["theme_id"],
               status=row.get("status", ""), checked_at=_now())
    notes: list[str] = []
    series: list[tuple[str, str, list[dict]]] = []
    if row.get("status") == "excluded":
        cov["notes"] = "universe v1 已剔除，不拉取"
        return cov, series

    if U.in_panel(row):
        chain = U.RESEARCH_CHAIN.get(row.get("research_route") or "")
        code = row.get("research_index_code") or ""
        if not chain:
            cov["error"] = f"未知 research_route {row.get('research_route')!r}"
        else:
            used = None                                 # (code, route, Fetched, price_only)
            tr, tr_notes = detect_tr(row, chain[0], end)
            notes += tr_notes
            if tr:
                r, got, errs = fetch_chain([chain[0]], tr, start, end)
                if got:
                    used = (tr, r, got, "False")
                    cov["tr_code_used"] = tr
                else:
                    notes.append(f"全收益 {tr} 全历史拉取失败（{'; '.join(errs)[:160]}）")
            if used is None and code in U.DECLARED_FALLBACK:
                fcode, froute = U.DECLARED_FALLBACK[code]
                r, got, errs = fetch_chain([froute], fcode, start, end)
                if got:
                    used = (fcode, r, got, "False")
                    notes.append(f"未得全收益版本，按 replan §1 改用 {fcode} 后复权（研究 = 执行）")
                else:
                    notes.append(f"声明的替代 {fcode} 后复权不可得（{'; '.join(errs)[:160]}）")
            price, price_errs = None, []
            if used is None or full:
                r, got, price_errs = fetch_chain(chain, code, start, end)
                if got:
                    price = (code, r, got, price_only_flag(row))
            if used is None:
                used = price
            if used:
                ucode, uroute, got, price_only = used
                cov.update(route_used=uroute, series_code=ucode, series_adj=store.adj_of(uroute),
                           series_name=got.name or "", first_date=got.rows[0]["date"], last_date=got.rows[-1]["date"],
                           rows=len(got.rows), price_only=price_only, max_gap_days=max_gap(got.rows)[0],
                           ohlc_missing_rows=_missing(got.rows, ("open", "high", "low")),
                           volume_missing_rows=_missing(got.rows, ("volume",)))
                if price:
                    cov["price_first_date"] = price[2].rows[0]["date"]
                if price_errs and used is price:
                    notes.append("前序路由失败：" + "; ".join(price_errs)[:200])
                if got.dropped:
                    notes.append(f"丢弃未收盘 K 线 {got.dropped} 行")
                notes += got.warnings
                g = gap_note(got.rows)
                if g:
                    notes.append(g)
                series.append((ucode, uroute, got.rows))
                if price and price is not used:
                    series.append((price[0], price[1], price[2].rows))
            else:
                cov["error"] = "; ".join(price_errs)[:400] or "无可用路由"
                alt = U.INFO_ALTERNATIVE.get(code)
                if alt:
                    r, got, errs = fetch_chain([alt[1]], alt[0], end - timedelta(days=PROBE_WINDOW_DAYS), end)
                    notes.append(f"近似指数 {alt[0]} {'可得' if got else '也不可得'}；未自动采用"
                                 f"（AGENTS.md 禁止近似指数替代，是否采用由 Cowork 决定）")
            if code in NOT_ATTEMPTED:
                notes.append(NOT_ATTEMPTED[code])
    else:
        notes.append("只作执行、不进面板")

    ex = row.get("execution_fund_code") or ""
    if ex:
        cov["exec_code"] = ex
        b = (exec_start or start) if full else end - timedelta(days=PROBE_WINDOW_DAYS)
        r, got, errs = fetch_chain(U.EXEC_CHAIN, ex, b, end)
        if got:
            cov.update(exec_route=r, exec_last_date=got.rows[-1]["date"])
            if full:
                cov.update(exec_first_date=got.rows[0]["date"], exec_rows=len(got.rows))
                series.append((ex, r, got.rows))
                g = gap_note(got.rows, "执行序列")
                if g:
                    notes.append(g)
            if errs:
                notes.append("执行序列前序路由失败：" + "; ".join(errs)[:160])
        else:
            cov["exec_error"] = "; ".join(errs)[:400]
        if not full:
            notes.append(f"执行 ETF 只查最近 {PROBE_WINDOW_DAYS} 天")
    cov["notes"] = " | ".join(notes)
    return cov, series


# ------------------------------------------------------------------ 作业
def _select(uni: list[dict], only: list[str] | None) -> list[dict]:
    if not only:
        return uni
    unknown = set(only) - {r["theme_id"] for r in uni}
    if unknown:
        raise SystemExit(f"universe 里没有：{sorted(unknown)}")
    return [r for r in uni if r["theme_id"] in only]


def _line(cov: dict) -> str:
    if cov["error"]:
        return f"  ERR {cov['theme_id']} {cov['container']}: {cov['error'][:120]}"
    if cov["route_used"]:
        tr = f" tr={cov['tr_code_used']}" if cov["tr_code_used"] else (" price_only" if cov["price_only"] == "True" else "")
        return (f"  ok  {cov['theme_id']} {cov['container']}: {cov['route_used']} {cov['series_code']}{tr} "
                f"{cov['first_date']}→{cov['last_date']} {cov['rows']} 行; 执行 {cov['exec_route'] or 'ERR'}")
    return f"  --  {cov['theme_id']} {cov['container']}: {cov['notes'][:100]}"


@contextmanager
def _job(db, kind: str, *, end: date | None = None, args: dict | None = None, uni_path: Path = U.UNIVERSE, create: bool = True):
    """打开库 → 装入 universe seed（记 sha256）→ runs 记一行；正常结束记 ok，异常记 error 后照常抛出。
    create=False（update、calendar）：库不存在就拒绝，不建空库（S1 之前的机器上留下未跟踪的库文件，之后 git pull 会冲突）。"""
    DB.refuse_default_in_tests(db, DB.MARKET_DB)
    if not create and not Path(db).exists():
        raise SystemExit(f"{db} 不存在：先跑 probe / backfill")
    con = DB.connect(db)
    try:
        uni = U.load(uni_path)
        sha = DB.sha256_file(uni_path)
        DB.load_universe(con, uni, sha)
        run_id = DB.start_run(con, kind, end=end, args=args, universe_sha256=sha)
        try:
            yield con, run_id, uni
        except BaseException as e:
            con.rollback()
            DB.finish_run(con, run_id, f"error: {type(e).__name__}: {str(e)[:200]}")
            raise
        DB.finish_run(con, run_id, "ok")
    finally:
        con.close()


def probe(end: date, *, start: date = DEFAULT_START, only=None, uni_path: Path = U.UNIVERSE,
          db: Path = DB.MARKET_DB, record: Path | None = None, log=print) -> list[dict]:
    http.LOG.clear()
    http.RECORD_DIR = record
    with _job(db, "probe", end=end, args={"start": start, "only": only, "record": record}, uni_path=uni_path) as (con, run_id, uni):
        covs = []
        for row in _select(uni, only):
            cov, _ = collect(row, start, end, full=False)
            covs.append(cov)
            log(_line(cov))
        DB.write_coverage(con, run_id, covs)
        DB.write_requests(con, run_id, http.LOG)
    return covs


def backfill(end: date, *, start: date = DEFAULT_START, exec_start: date | None = None, only=None, uni_path: Path = U.UNIVERSE,
             db: Path = DB.MARKET_DB, log=print) -> list[dict]:
    """exec_start 只缩短执行 ETF 的起点（减少东财上市前的空段请求）；研究序列始终从 start 拉，不丢设计期。
    每条拉到的序列整条替换库里的同一序列（code, adj）。"""
    http.LOG.clear()
    with _job(db, "backfill", end=end, args={"start": start, "exec_start": exec_start, "only": only}, uni_path=uni_path) as (con, run_id, uni):
        covs = []
        for row in _select(uni, only):
            cov, series = collect(row, start, end, full=True, exec_start=exec_start)
            at = _now()
            for code, route, rows in series:
                store.replace(con, code, route, rows, at)
            covs.append(cov)
            log(_line(cov))
        DB.write_coverage(con, run_id, covs)
        DB.write_requests(con, run_id, http.LOG)
    return covs


def container_series(cov: dict, row: dict) -> list[tuple[str, str, str]]:
    """(kind, code, adj)：研究序列、价格序列（若另有）、执行序列。"""
    out = []
    if cov.get("series_code") and cov.get("series_adj"):
        out.append(("research", cov["series_code"], cov["series_adj"]))
    chain = U.RESEARCH_CHAIN.get(row.get("research_route") or "")
    code = row.get("research_index_code") or ""
    if chain and code and code != cov.get("series_code"):
        out.append(("price", code, store.adj_of(chain[0])))
    if cov.get("exec_code"):
        out.append(("exec", cov["exec_code"], "raw"))
    return out


def _refresh(cov: dict, con) -> None:
    """按库里的序列重算起止日期与行数；序列不在则清空（不留与库不符的旧值）。"""
    for prefix, code, adj in (("", cov.get("series_code"), cov.get("series_adj")), ("exec_", cov.get("exec_code"), "raw")):
        if not code or not adj:
            continue
        sp = store.span(con, code, adj)
        cov.update({f"{prefix}first_date": sp["first"] or "", f"{prefix}last_date": sp["last"] or "",
                    f"{prefix}rows": sp["rows"] or ""})
        if prefix and sp["rows"]:
            cov["exec_route"] = sp["source"]


def update(end: date, *, only=None, uni_path: Path = U.UNIVERSE, db: Path = DB.MARKET_DB, log=print) -> list[dict]:
    """按每条序列已有的来源增量更新；不换路由（换了就不是同一条序列）。"""
    http.LOG.clear()
    with _job(db, "update", end=end, args={"only": only}, uni_path=uni_path, create=False) as (con, run_id, uni):
        covs = {c["theme_id"]: c for c in DB.read_coverage(con)}
        if not covs:
            raise SystemExit("库里没有 coverage：先跑 backfill")
        report, touched = [], []
        for row in _select(uni, only):
            cov = covs.get(row["theme_id"])
            if not cov:
                continue
            seen = set()
            for kind, code, adj in container_series(cov, row):
                if (code, adj) in seen:
                    continue
                seen.add((code, adj))
                old = store.read(con, code, adj)
                if not old:
                    if kind == "research":        # coverage 指向的研究序列不在：多半是 backfill 之后又跑了 probe
                        report.append({"theme_id": row["theme_id"], "kind": kind, "code": code, "adj": adj, "ok": False,
                                       "error": "coverage 指向的研究序列不在库里：重跑 backfill"})
                        log(f"  ERR {row['theme_id']} {code}/{adj}: 序列不在库里，重跑 backfill")
                    continue
                route = store.source_of(old)
                ent = {"theme_id": row["theme_id"], "kind": kind, "code": code, "adj": adj, "route": route}
                fn = U.route_fn(route or "", code)
                since = date.fromisoformat(old[-1]["date"]) - timedelta(days=OVERLAP_DAYS)
                try:
                    if fn is None:
                        raise http.FetchError(f"无 {code} 在 {route} 的代码映射")
                    got = fn(since, end)
                    cutoff = last_complete(route).isoformat()
                    new = [r for r in got.rows if r["date"] <= cutoff]
                    merged, added, revised = store.merge(old, new, route)
                    strict = route in STRICT_ROUTES or (kind == "research" and code == cov.get("tr_code_used"))
                    if strict and revised:
                        raise store.MixError(f"重叠区 {revised} 行被改写：后复权 / 全收益序列的基准可能变了，不拼接，需重新全量 backfill")
                    store.upsert(con, code, route, new, _now())
                    ent.update(ok=True, since=since.isoformat(), added=added, revised=revised, last_date=merged[-1]["date"])
                    log(f"  ok  {row['theme_id']} {code}/{adj}: +{added} 行，修正 {revised} 行，至 {merged[-1]['date']}")
                except Exception as e:  # noqa: BLE001
                    ent.update(ok=False, error=str(e)[:300])
                    log(f"  ERR {row['theme_id']} {code}/{adj}: {str(e)[:120]}")
                report.append(ent)
            _refresh(cov, con)
            cov["checked_at"] = _now()
            touched.append(cov)
        DB.write_coverage(con, run_id, touched)
        DB.write_update_results(con, run_id, report)
        DB.write_requests(con, run_id, http.LOG)
    return report


def load_calendar(path: Path, *, replace: bool = False, uni_path: Path = U.UNIVERSE, db: Path = DB.MARKET_DB, log=print) -> int:
    """astra 生成的交易日清单 → calendar 表。默认与库里已有的日子取并集（每年补一次）；replace=True 整表换成该文件。
    文件或并集不像交易日历（一行多列、非日期行、周末、中间缺一段）就拒绝，库不动。返回表里的交易日数。"""
    from src.indicators.calendar import check_days, read_calendar_file      # 指标层依赖数据层，这里按需引入免得循环
    try:
        days = read_calendar_file(path)
    except ValueError as e:
        raise SystemExit(f"交易日清单不可用，库未动：{e}")
    with _job(db, "calendar", args={"file": str(path), "sha256": DB.sha256_file(path), "replace": replace}, uni_path=uni_path,
              create=False) as (con, _, _u):
        have = [] if replace else [r[0] for r in con.execute("SELECT date FROM calendar")]
        try:
            union = check_days(list(days) + have, "交易日历（并入后）")
        except ValueError as e:
            raise SystemExit(f"并入后不像交易日历，库未动：{e}")
        with con:
            if replace:
                con.execute("DELETE FROM calendar")
            con.executemany("INSERT OR IGNORE INTO calendar (date) VALUES (?)", [(d.date().isoformat(),) for d in union])
        n = con.execute("SELECT count(*) FROM calendar").fetchone()[0]
    log(f"  交易日历 {n} 天：{union[0].date()} → {union[-1].date()}")
    return n


# ------------------------------------------------------------------ 研究数据包
def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def manifest_path(pkg: Path) -> Path:
    return Path(pkg).with_name(Path(pkg).stem + ".MANIFEST.json")


PACKAGE_CONTENT = {"meta": "key", "package": "key", "universe": "ord", "calendar": "date", "coverage": "theme_id",
                   "bars": "code, adj, date"}           # content_sha256 的范围：包内 runs（作业时刻）不算内容


def package(end: date, *, db: Path = DB.MARKET_DB, pkg_root: Path = PKG_ROOT, force: bool = False, log=print) -> Path:
    """从库复制一份截到 end 的只读库。只读源库（Cowork 在本地打包不改动入 Git 的库）；这次打包记在包内的 runs 与 package 表。
    coverage 与 bars 必须一致（研究序列存在、有行、source = route_used），否则该容器改记 error，列进 inconsistent_with_bars。
    包内容（除作业时刻外）只由源库、end 与 git commit 决定：content_sha256 在任何机器上可复现，prereg §13 记它；
    打包时刻只写在 MANIFEST.json。中途出错不留半截包。"""
    src_path = Path(db)
    DB.refuse_default_in_tests(src_path, DB.MARKET_DB)
    if not src_path.exists():
        raise SystemExit(f"{src_path} 不存在：先跑 backfill")
    safe = min(last_complete("csi"), last_complete("yahoo"))
    if end > safe:
        raise SystemExit(f"end={end} 尚未全部收盘（A 股与海外都收盘后的最近日期是 {safe}）；等收盘后再打包")
    src_sha = DB.sha256_file(src_path)
    src = DB.connect(src_path, readonly=True)
    try:
        covs = DB.read_coverage(src)
        if not covs:
            raise SystemExit("库里没有 coverage：先跑 backfill")
        uni_rows = [(r["ord"], r["theme_id"], r["row"]) for r in src.execute("SELECT ord, theme_id, row FROM universe ORDER BY ord")]
        uni = {tid: json.loads(row) for _, tid, row in uni_rows}
        missing = sorted({c["theme_id"] for c in covs} - set(uni))
        if missing:                                   # 价格版本序列（I-21 借量）靠 universe 认出；缺了会被静默漏掉
            raise SystemExit(f"库里的 universe 表缺 {missing[:5]}：先跑一次 probe / backfill 装入 seed")
        dest = Path(pkg_root) / f"research-package-{end.isoformat()}.sqlite"
        man = manifest_path(dest)
        if dest.exists() or man.exists():
            if not force:
                raise SystemExit(f"{dest} 已存在；确需重建加 --force")
            for p in (dest, man):
                if p.exists():
                    p.chmod(0o644)
                    p.unlink()
        uni_sha = (src.execute("SELECT value FROM meta WHERE key = 'universe_sha256'").fetchone() or [None])[0]
        wanted, inconsistent = [], []
        for c in covs:
            if c.get("series_adj"):                   # coverage 与 bars 必须一致，否则这一行按 error 处理
                sp = store.span(src, c["series_code"], c["series_adj"])
                if not sp["rows"] or sp["sources"] != 1 or sp["source"] != c.get("route_used"):
                    inconsistent.append(c["theme_id"])
                    why = "不在库里" if not sp["rows"] else f"来源 {sp['source']} ≠ route_used {c.get('route_used')}"
                    c["error"] = f"package: {c['series_code']}/{c['series_adj']} {why}（coverage 与 bars 不一致，重跑 backfill）"
                    for k in ("route_used", "series_code", "series_adj", "tr_code_used", "price_only", "first_date", "last_date", "rows"):
                        c[k] = ""
            wanted += [(code, adj) for _, code, adj in container_series(c, uni.get(c["theme_id"], {})) if (code, adj) not in wanted]
        Path(pkg_root).mkdir(parents=True, exist_ok=True)
        try:
            n, info = _write_package(src, dest, end, covs, wanted, uni_rows, uni_sha, inconsistent,
                                     {"source_db": _rel(src_path), "source_db_sha256": src_sha,
                                      "source_db_matches_commit": DB.git_clean(src_path)}, force)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    finally:
        src.close()
    os.chmod(dest, 0o444)
    con = DB.connect(dest, readonly=True)
    try:
        content = DB.content_sha256(con, PACKAGE_CONTENT)
    finally:
        con.close()
    meta = {"file": dest.name, "sha256": DB.sha256_file(dest), "content_sha256": content, "created_at": _now(), **info,
            "verify": f"python -m src.data verify {dest.name}"}
    man.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"  研究数据包 {dest}：{n} 条序列，面板容器 {info['with_series']}/{info['panel_containers']} 有数据；content_sha256 {content[:12]}…")
    return dest


def _write_package(src, dest: Path, end: date, covs: list[dict], wanted, uni_rows, uni_sha, inconsistent, source: dict, force: bool):
    pkg = DB.connect(dest, schema=DB.SCHEMA + DB.PACKAGE_SCHEMA)
    try:
        n = 0
        with pkg:
            for code, adj in wanted:
                rows = src.execute("SELECT code, adj, date, open, high, low, close, volume, amount, source, fetched_at FROM bars "
                                   "WHERE code = ? AND adj = ? AND date <= ? ORDER BY date", (code, adj, end.isoformat())).fetchall()
                if rows:
                    pkg.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [tuple(r) for r in rows])
                    n += 1
            pkg.executemany("INSERT INTO universe (ord, theme_id, row) VALUES (?, ?, ?)", uni_rows)
            pkg.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('universe_sha256', ?)", (uni_sha or "",))
            pkg.executemany("INSERT INTO calendar (date) VALUES (?)", [(r[0],) for r in src.execute("SELECT date FROM calendar ORDER BY date")])
        for c in covs:
            _refresh(c, pkg)
        run_id = DB.start_run(pkg, "package", end=end, args={"source_db": source["source_db"], "force": force}, universe_sha256=uni_sha)
        DB.write_coverage(pkg, run_id, covs)
        panel = [c for c in covs if c.get("status") in U.PANEL_STATUSES]
        info = {"end": end.isoformat(), "git_commit": DB.git_head(), **source, "universe_sha256": uni_sha,
                "series": n, "panel_containers": len(panel), "with_series": sum(1 for c in panel if c.get("rows")),
                "inconsistent_with_bars": inconsistent, "price_only": sum(1 for c in panel if c.get("price_only") == "True"),
                "calendar_days": pkg.execute("SELECT count(*) FROM calendar").fetchone()[0]}
        with pkg:
            pkg.executemany("INSERT INTO package (key, value) VALUES (?, ?)",
                            [(k, json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v) for k, v in info.items()])
        DB.finish_run(pkg, run_id, "ok")
        pkg.execute("VACUUM")
    finally:
        pkg.close()
    return n, info


def package_info(con) -> dict:
    """包内 package 表 → dict（数值与列表按 JSON 还原）。"""
    out = {}
    for k, v in con.execute("SELECT key, value FROM package"):
        try:
            out[k] = json.loads(v) if k not in ("end", "created_at", "git_commit", "source_db", "source_db_sha256", "universe_sha256") else v
        except json.JSONDecodeError:
            out[k] = v
    return out


def verify(path: Path) -> list[str]:
    """研究数据包复验；返回问题列表（空 = 通过），坏库与坏清单也只记问题、不抛异常。
    文件 sha256 与内容 content_sha256 对 MANIFEST.json、PRAGMA integrity_check、bars 行数对 coverage、无晚于 end 的行、
    source = route_used（执行序列对 exec_route）、没有 coverage 未引用的序列。
    MANIFEST 在包旁边，连同它一起改写的篡改发现不了：可信的锚点是 prereg §13 记下的 content_sha256。"""
    path = Path(path)
    if not path.exists():
        return [f"缺文件 {path.name}"]
    problems, manifest = [], {}
    man = manifest_path(path)
    if not man.exists():
        problems.append(f"缺 {man.name}")
    else:
        try:
            manifest = json.loads(man.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            problems.append(f"{man.name} 不是合法 JSON：{str(e)[:80]}")
        if manifest and manifest.get("sha256") != DB.sha256_file(path):
            problems.append(f"哈希不符 {path.name}")
    try:
        con = DB.connect(path, readonly=True)
    except Exception as e:  # noqa: BLE001 — 不是 SQLite 库 / schema 不对
        return problems + [f"打不开：{str(e)[:160]}"]
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            return problems + [f"integrity_check：{ok[:160]}"]
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'package'").fetchone():
            return problems + ["没有 package 表：不是研究数据包"]
        if manifest.get("content_sha256") and manifest["content_sha256"] != DB.content_sha256(con, PACKAGE_CONTENT):
            problems.append(f"内容哈希不符 {path.name}")
        info = package_info(con)
        end = info.get("end")
        if not end:
            return problems + ["package 表里没有 end"]
        late = con.execute("SELECT count(*), min(code) FROM bars WHERE date > ?", (end,)).fetchone()
        if late[0]:
            problems.append(f"有 {late[0]} 行晚于 end={end}（如 {late[1]}）")
        uni = {r["theme_id"]: json.loads(r["row"]) for r in con.execute("SELECT theme_id, row FROM universe")}
        referenced = set()
        for c in DB.read_coverage(con):
            referenced |= {(code, adj) for _, code, adj in container_series(c, uni.get(c["theme_id"], {}))}
            checks = [("", c.get("series_code"), c.get("series_adj"), c.get("route_used")),
                      ("exec_", c.get("exec_code"), "raw" if c.get("exec_rows") else "", c.get("exec_route"))]
            for prefix, code, adj, route in checks:
                if not code or not adj:
                    continue
                sp = store.span(con, code, adj)
                if str(sp["rows"] or "") != str(c.get(f"{prefix}rows") or ""):
                    problems.append(f"行数不符 {c['theme_id']} {code}/{adj}：bars {sp['rows']}，coverage {c.get(f'{prefix}rows')}")
                if sp["rows"] and (sp["sources"] != 1 or sp["source"] != route):
                    problems.append(f"来源不符 {c['theme_id']} {code}/{adj}：bars {sp['source']}，coverage {route}")
        have = {(r[0], r[1]) for r in con.execute("SELECT DISTINCT code, adj FROM bars")}
        problems += [f"清单外序列 {code}/{adj}" for code, adj in sorted(have - referenced)]
    except sqlite3.DatabaseError as e:              # 页面损坏等：integrity_check 之外的读取也可能直接报错
        problems.append(f"读取失败：{str(e)[:160]}")
    finally:
        con.close()
    return problems


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def compare(ref: Path, code: str, *, adj: str = "raw", db: Path = DB.MARKET_DB, tol: float = 0.0015, out: Path | None = None) -> dict:
    """重叠区间逐日比对收盘价（如 09-14 腾讯快照 data/kline_*.csv vs 库里的序列 code/adj）。
    差值 = 库 − ref；tol 默认 1.5 个最小价位（0.001），避免三位小数的四舍五入被当成阶跃。腾讯 qfq 是减法复权：与不复权相比，差值在两次除息之间恒定、除息日跳变，最后一次除息后为 0；
    列出差值变化的日期（候选除息日）逐条解释，其余不一致需人工查。"""
    a = {r["date"][:10]: float(r["close"]) for r in _read_csv(ref) if r.get("close")}
    con = DB.connect(db, readonly=True)
    try:
        b = {r["date"]: r["close"] for r in store.read(con, code, adj) if r.get("close") is not None}
    finally:
        con.close()
    days = sorted(set(a) & set(b))
    diffs = [(d, a[d], b[d], round(b[d] - a[d], 6)) for d in days]
    steps = [{"date": q[0], "diff_before": p[3], "diff_after": q[3]} for p, q in zip(diffs, diffs[1:]) if abs(q[3] - p[3]) > tol]
    res = {"overlap": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
           "equal": sum(1 for x in diffs if abs(x[3]) <= tol), "max_abs_diff": max((abs(x[3]) for x in diffs), default=0.0),
           "steps": steps}
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["date", "ref_close", "db_close", "diff"])
            w.writerows(diffs)
    return res
