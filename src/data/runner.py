"""probe / backfill / update / package / verify / compare。

probe     对 universe 每一行试路由，写 outputs/data/coverage.csv（数据源可用性的最小验证，也是 R0「核实」的最终形式）。
backfill  全量拉到 data/raw/（不入 Git），同时写 coverage。
update    按已有文件的来源增量拉取，往回多拉 OVERLAP_DAYS 天覆盖修正。
package   导出 outputs/research-package-<end>/：raw（截到 end）+ coverage + universe + MANIFEST（sha256）。
拿不到的容器只记一行 error 跳过，不阻塞其他容器（replan §6.4）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import http, store
from . import universe as U

ROOT = U.ROOT
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "outputs" / "data"
PKG_ROOT = ROOT / "outputs"
DEFAULT_START = date(2000, 1, 1)
PROBE_WINDOW_DAYS = 45       # 全收益候选与执行 ETF 只看最近一段：确认存在与名称
OVERLAP_DAYS = 10
MAX_GAP_DAYS = 20            # 超过即在 notes 提示（春节长假约 10 天）
INDEX_ROUTES = {"csi", "eastmoney_index", "yahoo"}     # universe 路由里属于价格指数的：无全收益版本即 price_only
A_SHARE_ROUTES = {"csi", "eastmoney_index", "tencent_index", "eastmoney_etf_hfq", "eastmoney_etf", "tencent_etf"}
STRICT_ROUTES = {"eastmoney_etf_hfq"}   # 后复权：重叠区被改写 = 复权基准变了，不能拼接
NOT_ATTEMPTED = {"518880": "上海金 Au99.99 未尝试：固定源与 replan 均未给出接口"}

COVERAGE_COLUMNS = [
    "container", "code", "route_used", "first_date", "last_date", "rows", "tr_code_used", "price_only", "error",
    "theme_id", "status", "series_code", "series_file", "series_name",
    "max_gap_days", "price_first_date", "ohlc_missing_rows", "volume_missing_rows",
    "exec_code", "exec_route", "exec_first_date", "exec_last_date", "exec_rows", "exec_error", "checked_at", "notes",
]
_TR_MARK = re.compile(r"全收益|财富|total\s*return|\bN?TR\b", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def last_complete(route: str, now: datetime | None = None) -> date:
    """该路由最近一根已收盘日线的日期：A 股按北京时间 15:30，海外按纽约时间 17:00（亚洲海外指数更早收盘，按纽约算只会更保守）。
    抓取时比它新的 K 线是盘中实时值，一律丢弃，不进 raw、更不进数据包。"""
    now = now or _utcnow()
    if route in A_SHARE_ROUTES:
        t, cut = now.astimezone(ZoneInfo("Asia/Shanghai")), time(15, 30)
    else:
        t, cut = now.astimezone(ZoneInfo("America/New_York")), time(17, 0)
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


def collect(row: dict, start: date, end: date, *, full: bool) -> tuple[dict, list[tuple[str, str, list[dict]]]]:
    """一个容器 → (coverage 行, 要落盘的序列 [(code, route, rows)])。
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
                cov.update(route_used=uroute, series_code=ucode, series_file=store.file_name(ucode, uroute),
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
        b = start if full else end - timedelta(days=PROBE_WINDOW_DAYS)
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


# ------------------------------------------------------------------ coverage 文件
def read_coverage(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_coverage(path: Path, rows: list[dict], order: list[str]) -> None:
    """按 universe 顺序写；只跑了部分容器（--only）时保留其余容器的旧行。"""
    by = {r["theme_id"]: r for r in read_coverage(path)}
    by.update({r["theme_id"]: r for r in rows})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COVERAGE_COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for tid in order + sorted(set(by) - set(order)):
            if tid in by:
                w.writerow(by[tid])


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


def _write_requests(out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / name, "w", encoding="utf-8") as f:
        for ent in http.LOG:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ 命令
def probe(end: date, *, start: date = DEFAULT_START, only=None, uni_path: Path = U.UNIVERSE,
          out_dir: Path = OUT_DIR, record: Path | None = None, log=print) -> list[dict]:
    uni = U.load(uni_path)
    http.LOG.clear()
    http.RECORD_DIR = record
    covs = []
    for row in _select(uni, only):
        cov, _ = collect(row, start, end, full=False)
        covs.append(cov)
        log(_line(cov))
    write_coverage(out_dir / "coverage.csv", covs, [r["theme_id"] for r in uni])
    _write_requests(out_dir, "probe-requests.jsonl")
    return covs


def backfill(end: date, *, start: date = DEFAULT_START, only=None, uni_path: Path = U.UNIVERSE,
             raw_dir: Path = RAW_DIR, out_dir: Path = OUT_DIR, log=print) -> list[dict]:
    uni = U.load(uni_path)
    http.LOG.clear()
    covs = []
    for row in _select(uni, only):
        cov, series = collect(row, start, end, full=True)
        for code, route, rows in series:
            store.write(raw_dir / store.file_name(code, route), [{**r, "source": route} for r in rows])
        covs.append(cov)
        log(_line(cov))
    write_coverage(out_dir / "coverage.csv", covs, [r["theme_id"] for r in uni])
    _write_requests(out_dir, "backfill-requests.jsonl")
    return covs


def _container_files(cov: dict, row: dict) -> list[tuple[str, str, str]]:
    """(kind, code, file)：研究序列、价格序列（若另有）、执行序列。"""
    out = []
    if cov.get("series_file"):
        out.append(("research", cov["series_code"], cov["series_file"]))
    chain = U.RESEARCH_CHAIN.get(row.get("research_route") or "")
    code = row.get("research_index_code") or ""
    if chain and code and code != cov.get("series_code"):
        out.append(("price", code, store.file_name(code, chain[0])))
    if cov.get("exec_code"):
        out.append(("exec", cov["exec_code"], store.file_name(cov["exec_code"], "eastmoney_etf")))
    return out


def _refresh(cov: dict, raw_dir: Path) -> None:
    """按 raw_dir 里的文件重算起止日期与行数；文件不存在则清空（不留与文件不符的旧值）。"""
    exec_file = store.file_name(cov["exec_code"], "eastmoney_etf") if cov.get("exec_code") else ""
    for prefix, fname in (("", cov.get("series_file")), ("exec_", exec_file)):
        if not fname:
            continue
        rows = store.read(raw_dir / fname)
        cov.update({f"{prefix}first_date": rows[0]["date"] if rows else "", f"{prefix}last_date": rows[-1]["date"] if rows else "",
                    f"{prefix}rows": len(rows) if rows else ""})
        if prefix and rows:
            cov["exec_route"] = store.source_of(rows) or cov.get("exec_route", "")


def update(end: date, *, only=None, uni_path: Path = U.UNIVERSE, raw_dir: Path = RAW_DIR,
           out_dir: Path = OUT_DIR, log=print) -> list[dict]:
    """按每个文件已有的来源增量更新；不换路由（换了就不是同一条序列）。"""
    uni = U.load(uni_path)
    covs = {c["theme_id"]: c for c in read_coverage(out_dir / "coverage.csv")}
    if not covs:
        raise SystemExit("没有 outputs/data/coverage.csv：先跑 backfill")
    http.LOG.clear()
    report = []
    for row in _select(uni, only):
        cov = covs.get(row["theme_id"])
        if not cov:
            continue
        seen = set()
        for kind, code, fname in _container_files(cov, row):
            path = raw_dir / fname
            if fname in seen:
                continue
            seen.add(fname)
            if not path.exists():
                if kind == "research":        # coverage 指向的研究序列不在：多半是 backfill 之后又跑了 probe
                    report.append({"at": _now(), "theme_id": row["theme_id"], "kind": kind, "file": fname, "ok": False,
                                   "error": "coverage 指向的研究序列文件不存在：重跑 backfill"})
                    log(f"  ERR {row['theme_id']} {fname}: 文件不存在，重跑 backfill")
                continue
            old = store.read(path)
            route = store.source_of(old)
            ent = {"at": _now(), "theme_id": row["theme_id"], "kind": kind, "file": fname, "route": route}
            fn = U.route_fn(route or "", code)
            since = date.fromisoformat(old[-1]["date"]) - timedelta(days=OVERLAP_DAYS) if old else DEFAULT_START
            try:
                if fn is None:
                    raise http.FetchError(f"无 {code} 在 {route} 的代码映射")
                got = fn(since, end)
                cutoff = last_complete(route).isoformat()
                merged, added, revised = store.merge(old, [r for r in got.rows if r["date"] <= cutoff], route)
                strict = route in STRICT_ROUTES or (kind == "research" and code == cov.get("tr_code_used"))
                if strict and revised:
                    raise store.MixError(f"重叠区 {revised} 行被改写：后复权 / 全收益序列的基准可能变了，不拼接，需重新全量 backfill")
                store.write(path, merged)
                ent.update(ok=True, since=since.isoformat(), added=added, revised=revised, last_date=merged[-1]["date"])
                log(f"  ok  {row['theme_id']} {fname}: +{added} 行，修正 {revised} 行，至 {merged[-1]['date']}")
            except Exception as e:  # noqa: BLE001
                ent.update(ok=False, error=str(e)[:300])
                log(f"  ERR {row['theme_id']} {fname}: {str(e)[:120]}")
            report.append(ent)
        _refresh(cov, raw_dir)
        cov["checked_at"] = _now()
    write_coverage(out_dir / "coverage.csv", list(covs.values()), [r["theme_id"] for r in uni])
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "update-log.jsonl", "a", encoding="utf-8") as f:
        for ent in report:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    with open(out_dir / "update-requests.jsonl", "a", encoding="utf-8") as f:
        for ent in http.LOG:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    return report


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def package(end: date, *, uni_path: Path = U.UNIVERSE, raw_dir: Path = RAW_DIR, out_dir: Path = OUT_DIR,
            pkg_root: Path = PKG_ROOT, force: bool = False, log=print) -> Path:
    covs = read_coverage(out_dir / "coverage.csv")
    if not covs:
        raise SystemExit("没有 outputs/data/coverage.csv：先跑 backfill")
    safe = min(last_complete("csi"), last_complete("yahoo"))
    if end > safe:
        raise SystemExit(f"end={end} 尚未全部收盘（A 股与海外都收盘后的最近日期是 {safe}）；等收盘后再打包")
    dest = pkg_root / f"research-package-{end.isoformat()}"
    if dest.exists():
        if not force:
            raise SystemExit(f"{dest} 已存在；确需重建加 --force")
        shutil.rmtree(dest)
    (dest / "raw").mkdir(parents=True)
    uni = {r["theme_id"]: r for r in U.load(uni_path)}
    wanted, inconsistent = set(), []
    for c in covs:
        if c.get("series_file"):                  # coverage 与 raw 必须一致，否则这一行按 error 处理
            rows = store.read(raw_dir / c["series_file"])
            src = store.source_of(rows) if rows else None
            if not rows or src != c.get("route_used"):
                inconsistent.append(c["theme_id"])
                why = "缺失" if not rows else f"来源 {src} ≠ route_used {c.get('route_used')}"
                c["error"] = f"package: {c['series_file']} {why}（coverage 与 raw 不一致，重跑 backfill）"
                for k in ("route_used", "series_code", "series_file", "tr_code_used", "price_only", "first_date", "last_date", "rows"):
                    c[k] = ""
        wanted |= {f for _, _, f in _container_files(c, uni.get(c["theme_id"], {}))}
    n = 0
    for fname in sorted(wanted):
        rows = [r for r in store.read(raw_dir / fname) if r["date"] <= end.isoformat()]
        if rows:
            store.write(dest / "raw" / fname, rows)
            n += 1
    for c in covs:
        _refresh(c, dest / "raw")
    write_coverage(dest / "coverage.csv", covs, [c["theme_id"] for c in covs])
    shutil.copyfile(uni_path, dest / "universe.csv")
    files = sorted(p for p in dest.rglob("*") if p.is_file())
    with open(dest / "MANIFEST.sha256", "w", encoding="utf-8", newline="\n") as f:
        for p in files:
            f.write(f"{_sha256(p)}  {p.relative_to(dest).as_posix()}\n")
    panel = [c for c in covs if c.get("status") in U.PANEL_STATUSES]
    meta = {"end": end.isoformat(), "created_at": _now(), "git_head": _git_head(), "raw_files": n,
            "universe_sha256": _sha256(dest / "universe.csv"),
            "panel_containers": len(panel), "with_series": sum(1 for c in panel if c.get("rows")),
            "inconsistent_with_raw": inconsistent,
            "price_only": sum(1 for c in panel if c.get("price_only") == "True"),
            "verify": "python -m src.data verify <本目录>  或  sha256sum -c MANIFEST.sha256"}
    (dest / "MANIFEST.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"  研究数据包 {dest}：{n} 个序列文件，面板容器 {meta['with_series']}/{meta['panel_containers']} 有数据")
    return dest


def verify(dest: Path) -> list[str]:
    """按 MANIFEST.sha256 复验；返回问题列表（空 = 通过）。"""
    man = dest / "MANIFEST.sha256"
    if not man.exists():
        return ["缺少 MANIFEST.sha256"]
    problems, listed = [], set()
    for line in man.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        listed.add(rel)
        p = dest / rel
        if not p.exists():
            problems.append(f"缺文件 {rel}")
        elif _sha256(p) != digest:
            problems.append(f"哈希不符 {rel}")
    extra = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()} - listed - {"MANIFEST.sha256", "MANIFEST.json"}
    problems += [f"清单外文件 {x}" for x in sorted(extra)]
    return problems


def compare(ref: Path, raw: Path, *, tol: float = 0.0015, out: Path | None = None) -> dict:
    """重叠区间逐日比对收盘价（如仓库 data/kline_*.csv 的 09-14 腾讯快照 vs data/raw）。
    差值 = raw − ref；tol 默认 1.5 个最小价位（0.001），避免三位小数的四舍五入被当成阶跃。腾讯 qfq 是减法复权：与不复权相比，差值在两次除息之间恒定、除息日跳变，最后一次除息后为 0；
    列出差值变化的日期（候选除息日）逐条解释，其余不一致需人工查。"""
    a = {r["date"][:10]: float(r["close"]) for r in store.read(ref) if r.get("close")}
    b = {r["date"][:10]: float(r["close"]) for r in store.read(raw) if r.get("close")}
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
            w.writerow(["date", "ref_close", "raw_close", "diff"])
            w.writerows(diffs)
    return res
