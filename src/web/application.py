"""HTTP 无关的薄应用层；不改冻结字段，不向浏览器投影 agent 个体评分。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time as wall
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data import db as MarketDB
from src.data.quality import preflight
from src.data.universe import PANEL_STATUSES
from src.indicators.build import BENCH_CODE
from src.indicators.calendar import load_trading_days
from src.jobs.daily import next_weekday_open
from src.jobs.rules import ACTIVE_BEFORE_V1, load_rule_config
from src.ledger.read import summary
from src.ledger.store import CARD_FIELDS, DEFAULT_DB, FROZEN_FIELDS, ROOT, SCHEMA_VERSION, Ledger, LedgerError, beijing_now
from src.scoring.review import counterfactual, review_report
from src.observation import observe
from .demo import DemoStore
from .demo_observation import demo_market
from .write_card import FormError, active_sources, assemble, panel_containers, source_grades


class RequestError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@contextmanager
def read_ledger(path: Path, *, replay=False):
    """不存在不创建；不调用会初始化 schema/固定源的 Ledger 构造器。"""
    if os.environ.get("ETF_LEDGER_TESTING") and path.resolve() == DEFAULT_DB.resolve():
        raise LedgerError("测试禁止访问正式台账")
    if not path.exists():
        yield None
        return
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only = ON")
        con.execute("BEGIN")
        meta = dict(con.execute("SELECT key, value FROM ledger_meta"))
        if meta.get("schema") != SCHEMA_VERSION or meta.get("clock") != ("replay" if replay else "real"):
            raise LedgerError("台账版本或时钟不符，只读入口不会升级或迁移")
        yield con
    finally:
        con.close()


def rows(con, sql, args=()):
    return [dict(row) for row in con.execute(sql, args)]


def one(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return dict(row) if row else None


def read_market(path: Path):
    """每次读取一致快照；只投影 bars 和 coverage 登记，不读取作业参数或台账。"""
    market = {"available": False, "series": [], "rows": 0, "first": None, "last": None}
    MarketDB.refuse_default_in_tests(path, MarketDB.MARKET_DB)
    if not path.exists():
        return market
    try:
        con = MarketDB.connect(path, readonly=True)
    except MarketDB.DbError:
        raise RequestError("行情版本不符；只读预览不执行迁移。", 503) from None
    try:
        con.execute("PRAGMA query_only = ON")
        con.execute("BEGIN")
        series = rows(con, """WITH counts AS (
            SELECT code,adj,count(*) AS count,min(date) AS first,max(date) AS last,
                   sum(open IS NULL) AS open_null,sum(high IS NULL) AS high_null,
                   sum(low IS NULL) AS low_null,sum(close IS NULL) AS close_null,
                   sum(open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL) AS ohlc_null,
                   sum(volume IS NULL) AS volume_null,sum(amount IS NULL) AS amount_null
            FROM bars GROUP BY code,adj)
            SELECT counts.*,b.close,b.source,b.volume,b.amount FROM counts JOIN bars b
            ON b.code=counts.code AND b.adj=counts.adj AND b.date=counts.last
            ORDER BY counts.code,counts.adj""")
        coverage = rows(con, """SELECT theme_id,container,code,series_code,series_adj,series_name,
            route_used,tr_code_used,price_only,exec_code,exec_route,status FROM coverage_latest ORDER BY theme_id""")
        for item in series:
            item.update(name=item["code"], containers=[], relationships=[], price_only=None,
                        type="未登记类型", research_selected=False)
            for cov in coverage:
                research = (item["code"] == cov["series_code"] and item["adj"] == cov["series_adj"]
                            and item["source"] == cov["route_used"])
                execution = (item["code"] == cov["exec_code"] and item["adj"] == "raw"
                             and item["source"] == cov["exec_route"])
                if item["code"] in (cov["code"], cov["series_code"], cov["exec_code"]):
                    if cov["container"] and cov["container"] not in item["containers"]:
                        item["containers"].append(cov["container"])
                if research or execution:
                    item["relationships"].append({"theme_id": cov["theme_id"], "status": cov["status"],
                                                  "role": "research" if research else "execution"})
                if research:
                    item["research_selected"] = True
                    item["name"] = cov["series_name"] or item["code"]
                    item["price_only"] = {"True": True, "False": False}.get(cov["price_only"])
                    item["type"] = ("全收益指数" if cov["tr_code_used"] == item["code"] else
                                    "价格指数" if item["price_only"] is True else "研究序列 · 类型未登记")
                elif execution:
                    item["type"] = "ETF · 不复权"
            if item["adj"] == "hfq":
                item["type"] = "ETF · 含分红后复权"
            if item["source"] == "tencent_price_index_offline" and item["code"] in ("000852", "000905"):
                item.update(price_only=True, research_selected=False, type="价格指数")
        market.update(available=True, series=series, rows=sum(s["count"] for s in series),
                      first=min((s["first"] for s in series), default=None),
                      last=max((s["last"] for s in series), default=None))
        return market
    finally:
        con.close()


class Application:
    def __init__(self, demo_dir=ROOT / "outputs" / "app-demo", *, mode="demo",
                 ledger_path=DEFAULT_DB, market_path=ROOT / "data" / "market.sqlite", demo_only=False,
                 write=False, write_token=None, clock=None):
        if mode not in ("demo", "readonly", "market"):
            raise ValueError("mode must be demo, readonly or market")
        if demo_only and mode != "demo":
            raise ValueError("纯演示服务只能使用 demo 模式")
        if demo_only and not Path(demo_dir).resolve().is_relative_to((ROOT / "outputs").resolve()):
            raise ValueError("纯演示目录必须位于 outputs 内")
        if write and mode != "readonly":
            raise ValueError("--write 只在 --mode readonly 下有效")
        if write and (not isinstance(write_token, str) or len(write_token) < 16):
            raise ValueError("开启 --write 必须设置环境变量 LEDGER_WRITE_TOKEN（至少 16 个字符）")
        if clock is not None and not write:
            raise ValueError("注入时钟只用于带 --write 的回放验收")
        if clock is not None and not _minute(clock):
            raise ValueError("时钟须为 YYYY-MM-DDTHH:MM")
        if clock is not None and Path(ledger_path).resolve() == DEFAULT_DB.resolve():
            raise ValueError("回放不能写正式台账库")
        self.mode, self.demo_only = mode, demo_only
        self.write, self.write_token, self.clock = bool(write), write_token, clock
        self.sessions: dict[str, float] = {}
        self.ledger_path, self.market_path = Path(ledger_path), Path(market_path)
        self.lock = threading.RLock()
        self.revision, self.csrf_token = ((None, None) if mode == "market" else
                                         (secrets.token_urlsafe(24), secrets.token_urlsafe(32)))
        self.demo = DemoStore(demo_dir) if mode == "demo" else None
        if self.demo:
            for path in (self.ledger_path, self.market_path):
                if (path.resolve() == self.demo.path.resolve() or
                        (path.exists() and self.demo.path.exists() and path.samefile(self.demo.path))):
                    raise LedgerError("演示与正式路径不能重合")
            self.demo.ensure()
        self._data_cache = None
        self._observation_cache = {}

    def effective_mode(self, mode):
        if mode not in (None, "demo", "readonly", "market"):
            raise RequestError("未知数据入口")
        if self.mode == "market" and mode not in (None, "market"):
            raise RequestError("行情只读服务不开放演示或正式台账入口", 403)
        if mode == "market" and self.mode != "market":
            raise RequestError("此服务未开放行情预览入口", 403)
        if self.demo_only and mode == "readonly":
            raise RequestError("纯演示服务不开放正式入口", 403)
        if self.mode == "readonly" and mode == "demo":
            raise RequestError("此服务仅开放只读入口", 403)
        return mode or self.mode

    def _reader(self, mode):
        mode = self.effective_mode(mode)
        if mode == "market":
            raise RequestError("行情只读服务不读取机会台账", 403)
        replay = mode == "demo" or (mode == "readonly" and self.clock is not None)
        return read_ledger(self.demo.path if mode == "demo" else self.ledger_path, replay=replay)

    def clock_text(self):
        return self.clock or beijing_now()

    def session_ok(self, token):
        if not token or not self.write:
            return False
        expiry = self.sessions.get(token)
        if not expiry or expiry < wall.time():
            self.sessions.pop(token, None)
            return False
        return True

    def _rotate(self):
        self.revision = secrets.token_urlsafe(24)

    def data_status(self):
        if self.demo_only or self.mode == "market":
            raise RequestError("此服务不执行正式行情预检", 403)
        stamp = (self.market_path.stat().st_mtime_ns, self.market_path.stat().st_size) if self.market_path.exists() else None
        today = beijing_now()[:10]
        key = (stamp, today)
        if self._data_cache is None or self._data_cache[0] != key:
            if stamp is None:
                report = {"benchmark_ready": False, "research_ready": False, "note": "正式行情库不存在，未创建文件。"}
            else:
                try:
                    report = preflight(self.market_path, date.fromisoformat(today))
                    report["note"] = "正式行情只读预检；演示序列与此独立。"
                except (ValueError, sqlite3.Error) as err:
                    report = {"benchmark_ready": False, "research_ready": False, "note": f"正式行情预检受阻：{err}"}
            self._data_cache = key, report
        return self._data_cache[1]

    def state(self, mode=None, session=None):
        with self.lock:
            mode = self.effective_mode(mode)
            if mode == "market":
                market = read_market(self.market_path)
                return {"mode": "market", "as_of": beijing_now(), "observation_as_of": market["last"],
                        "writable": False, "write_enabled": False, "authenticated": False,
                        "demo_available": False, "cards": [], "market": market,
                        "ledger_note": "此观察入口不载入正式判断/扫描结果。"}
            now = self.demo.now() if mode == "demo" else self.clock_text()
            cards = []
            unchecked = None
            observation_as_of = None
            review = None
            latest_processed_day = None
            totals = {"denominator": 0, "terminal": 0, "by_status": {}, "by_final_score": {},
                      "hit_rate_over_terminal": None, "manual_exit_share": None}
            with self._reader(mode) as con:
                if con:
                    latest_processed_day = con.execute("SELECT max(day) FROM job_days").fetchone()[0]
                    totals = summary(con)
                    review = review_report(con)
                    observation_as_of = con.execute("SELECT max(date) FROM daily").fetchone()[0]
                    cards = rows(con, """SELECT c.id,c.container,c.instrument_code,c.instrument_name,
                        s.status,c.thesis,c.trigger_type,c.created_at,c.close_date,c.owner_score_deadline,
                        c.thesis_inval_deadline AS next_observation,e.entry_date,x.exit_date,f.final_score,
                        (SELECT r_current FROM daily WHERE card_id=c.id ORDER BY date DESC LIMIT 1) AS r_current,
                        (SELECT close FROM daily WHERE card_id=c.id ORDER BY date DESC LIMIT 1) AS daily_close,
                        (SELECT date FROM daily WHERE card_id=c.id ORDER BY date DESC LIMIT 1) AS daily_date,
                        c.evidence_status
                        FROM cards c JOIN card_status s ON s.id=c.id
                        LEFT JOIN entries e ON e.card_id=c.id LEFT JOIN exits x ON x.card_id=c.id
                        LEFT JOIN finals f ON f.card_id=c.id WHERE c.sealed=1 ORDER BY c.created_at DESC,c.id DESC""")
                    unchecked = con.execute("""SELECT count(*) FROM cards c WHERE c.sealed = 1
                        AND NOT EXISTS (SELECT 1 FROM spot_checks s WHERE s.card_id = c.id)""").fetchone()[0]
            problems = []
            enabled = ["事件驱动"] if mode == "demo" else list(load_rule_config(ROOT / "config" / "ledger-rules.json", problems))
            authed = mode == "readonly" and self.session_ok(session)
            payload = {"mode": mode, "as_of": now, "observation_as_of": observation_as_of,
                    "unchecked": unchecked if mode != "market" else None,
                    "demo_available": self.demo is not None, "readonly_available": self.mode != "market" and not self.demo_only,
                    "writable": mode == "demo" or authed, "write_enabled": mode == "readonly" and self.write,
                    "authenticated": authed,
                    "revision": self.revision, "csrf_token": self.csrf_token, "cards": cards, "summary": totals, "review": review,
                    "scan": {"latest_processed_day": latest_processed_day,
                             "note": "配置启用不表示已扫描；此处仅报告台账已处理日。"},
                    "rules": {"enabled": enabled, "blocked": [] if mode == "demo" else [r for r in ACTIVE_BEFORE_V1 if r not in enabled] + ["形态突破"],
                              "note": "纯演示：仅使用独立合成事件输入，不读取正式规则。" if mode == "demo" else
                                      "；".join(problems) or "正式规则配置仅供查看，不表示已执行扫描。"},
                    "data_status": {"benchmark_ready": False, "research_ready": False,
                                    "note": "纯演示：行情全部合成，不读取正式数据库。"} if mode == "demo" else self.data_status()}
            if payload["write_enabled"]:
                payload["containers"] = panel_containers()
                payload["sources"] = active_sources()
            return payload

    def observation(self, mode=None, *, as_of=None, theme=None, series="execution", weeks=12):
        """页面只读投影；请求不能选择数据库、修改 coverage 或执行研究。"""
        mode = self.effective_mode(mode)
        try:
            requested = date.fromisoformat(as_of) if as_of else None
            if as_of and requested.isoformat() != as_of:
                raise ValueError()
        except (TypeError, ValueError):
            raise RequestError("观察日期须为有效的 YYYY-MM-DD") from None
        if series not in ("research", "execution", "price_candidate"):
            raise RequestError("未知价格序列用途")
        if not isinstance(weeks, int) or not 1 <= weeks <= 26:
            raise RequestError("周窗口须为 1–26")
        with self.lock:
            now = datetime.fromisoformat(self.demo.now() if mode == "demo" else self.clock_text()).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            stamp = None
            if mode != "demo":
                MarketDB.refuse_default_in_tests(self.market_path, MarketDB.MARKET_DB)
                if not self.market_path.exists():
                    raise RequestError("行情库不存在；只读入口未创建文件。", 503)
                stat = self.market_path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            # 模型只区分北京时间日期与 15:00 收盘边界，文件变化即失效。
            key = (mode, stamp, now.date(), now.time() >= time(15), as_of, theme, series, weeks)
            if key in self._observation_cache:
                return self._observation_cache[key]
            if mode == "demo":
                with demo_market() as con:
                    self._check_theme(con, theme)
                    result = observe(con, requested, now=now, weeks=weeks, theme_id=theme, series_kind=series)
                result["history_note"] = "全部行情为合成演示；日历为合成工作日，不是交易所日历。" + result.get("history_note", "")
            else:
                try:
                    con = MarketDB.connect(self.market_path, readonly=True)
                except MarketDB.DbError:
                    raise RequestError("行情版本不符；只读观察不执行迁移。", 503) from None
                try:
                    con.execute("PRAGMA query_only = ON")
                    con.execute("BEGIN")
                    self._check_theme(con, theme)
                    result = observe(con, requested, now=now, weeks=weeks, theme_id=theme, series_kind=series)
                finally:
                    con.close()
            result["mode"] = mode
            if len(self._observation_cache) >= 16:
                self._observation_cache.clear()
            self._observation_cache[key] = result
            return result

    @staticmethod
    def _check_theme(con, theme):
        if theme is not None:
            # 只读版本化声明；无效 ID 属于请求错误，不冒充库故障。
            row = con.execute("SELECT row FROM universe WHERE theme_id=?", (theme,)).fetchone()
            if row is None or json.loads(row[0]).get("status") not in PANEL_STATUSES:
                raise RequestError("未知容器编号")

    def detail(self, card_id, mode=None, session=None):
        with self.lock:
            mode = self.effective_mode(mode)
            with self._reader(mode) as con:
                card = one(con, f"SELECT {','.join(CARD_FIELDS)} FROM cards WHERE id=? AND sealed=1", (card_id,)) if con else None
                if not card:
                    raise RequestError("未找到卡片", 404)
                status = con.execute("SELECT status FROM card_status WHERE id=?", (card_id,)).fetchone()[0]
                parts = {name: one(con, f"SELECT * FROM {table} WHERE card_id=?", (card_id,))
                         for name, table in (("entry", "entries"), ("exit", "exits"), ("final", "finals"), ("void", "voids"))}
                daily = rows(con, "SELECT * FROM daily WHERE card_id=? ORDER BY date", (card_id,))
                signals = rows(con, "SELECT * FROM exit_signals WHERE card_id=? ORDER BY seq", (card_id,))
                agent = one(con, "SELECT score,reason,scored_at FROM strength_scores WHERE card_id=? AND rater='agent'", (card_id,))
                evidence = rows(con, "SELECT * FROM evidence WHERE card_id=? ORDER BY seq", (card_id,))
                checks = rows(con, "SELECT seq,verdict,note,checked_at FROM spot_checks WHERE card_id=? ORDER BY seq", (card_id,))
                comparisons = counterfactual(con, card_id)
            completed = sum(d["date"] > parts["exit"]["exit_date"] for d in daily) if parts["exit"] else 0
            signal_date = daily[-1]["date"] if daily else None
            can_signal = status == "当下" and bool(daily) and (not signals or
                len(signals) == 1 and signals[0]["reason"] in ("失效位", "移动止盈") and signals[0]["signal_date"] == signal_date)
            can = mode == "demo" or self.session_ok(session)
            return {"card": card, "status": status, **parts, "daily": daily, "evidence": evidence, "signals": signals,
                    "counterfactual": comparisons, "spot_checks": checks,
                    "scores": {"agent": agent},
                    "actions": {"can_spot": mode == "readonly" and self.session_ok(session),
                                "can_void": can and status == "候选",
                                "can_signal": can and can_signal,
                                "signal_date": signal_date},
                    "tracking": {"completed": completed, "required": card["tracking_days"]}}

    def mutate(self, action, body, *, card_id=None, mode=None, session=None):
        with self.lock:
            mode = self.effective_mode(mode)
            if mode == "demo":
                return self._mutate_demo(action, body, card_id=card_id, mode=mode)
            if not (mode == "readonly" and self.write and self.session_ok(session)):
                raise RequestError("正式入口只读", 403)
            if action == "create":
                created = self._create(body)
                self._rotate()
                return {**self.state(mode, session), "created_id": created}
            self._check_revision(body)
            if set(body) & set(FROZEN_FIELDS):
                raise RequestError("请求含不允许的字段；冻结字段不可修改")
            fields = {"void": {"reason"}, "exit-signal": {"reason", "manual_reason"}, "spot-check": {"verdict", "note"}}
            if action == "score":
                raise RequestError("owner 盲分已取消", 404)
            if action not in fields or not isinstance(body, dict) or set(body) - (fields[action] | {"revision"}):
                raise RequestError("请求含不允许的字段；冻结字段不可修改")
            with self._writer() as ledger:
                self._apply(ledger, action, body, card_id, self.detail(card_id, mode, session))
            self._rotate()
            return self.state(mode, session)

    def _mutate_demo(self, action, body, *, card_id, mode):
        fields = {"void": {"reason"}, "exit-signal": {"reason", "manual_reason"},
                  "spot-check": {"verdict", "note"}, "advance": set(), "reset": set()}
        if action not in fields:
            raise RequestError("未知操作", 404)
        if not isinstance(body, dict) or set(body) - (fields[action] | {"revision"}):
            raise RequestError("请求含不允许的字段；冻结字段不可修改")
        self._check_revision(body)
        if action in ("advance", "reset"):
            getattr(self.demo, action)()
        else:
            detail = self.detail(card_id, mode)
            with self.demo.open_ledger() as ledger:
                self._apply(ledger, action, body, card_id, detail)
        self._rotate()
        return self.state(mode)

    def _check_revision(self, body):
        if not isinstance(body, dict) or body.get("revision") != self.revision:
            raise RequestError("页面已更新，请刷新后重试", 409)

    def event_feed(self, day=None):
        """事件草稿的锁卡 / 退回。不要求登录，起草方靠它看反馈。"""
        mode = "demo" if self.mode == "demo" else "readonly"
        with self._reader(mode) as con:
            if con is None:
                return {"day": day, "drafts": [], "days": [], "note": "台账不存在"}
            days = [r[0] for r in con.execute("SELECT DISTINCT day FROM event_drafts ORDER BY day DESC")]
            chosen = day or (days[0] if days else None)
            if chosen and chosen not in days and day:
                drafts = []
            else:
                drafts = rows(con, """SELECT day, seq, container, outcome, reason, card_id, events_commit, file_sha256
                                       FROM event_drafts WHERE day = ? ORDER BY seq""", (chosen,)) if chosen else []
            return {"day": chosen, "drafts": drafts, "days": days}

    def _apply(self, ledger, action, body, card_id, detail):
        if action == "spot-check":
            if not detail["actions"]["can_spot"]:
                raise RequestError("登录后才能抽查", 403)
            verdict = body.get("verdict")
            note = body.get("note")
            if verdict not in ("无误", "有误"):
                raise RequestError("抽查结论只能是「无误」或「有误」")
            if not isinstance(note, str) or not note.strip() or len(note.strip()) > 200:
                raise RequestError("请写一句说明（1–200 字）")
            ledger.spot_check(card_id, verdict, note.strip())
            return
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise RequestError("请填写理由（1–2000 字）")
        if action == "void":
            ledger.void(card_id, reason)
        else:
            if reason not in ("手动", "论点作废") or not detail["actions"]["can_signal"]:
                raise RequestError("当前不能声明此出场信号")
            manual = body.get("manual_reason")
            if reason == "手动" and (not isinstance(manual, str) or not manual.strip() or len(manual) > 2000):
                raise RequestError("手动出场须填写理由（1–2000 字）")
            if reason == "论点作废" and manual is not None:
                raise RequestError("论点作废不接受手动出场理由")
            latest = detail["daily"][-1]
            ledger.signal_exit(card_id, latest["date"], reason, latest["close"], manual)

    def login(self, body):
        if not self.write:
            raise RequestError("未找到操作", 404)
        self._check_revision(body)
        if not isinstance(body, dict) or set(body) - {"password", "revision"}:
            raise RequestError("请求含不允许的字段")
        password = body.get("password")
        if not isinstance(password, str) or not hmac.compare_digest(
                hashlib.sha256(password.encode()).digest(), hashlib.sha256(self.write_token.encode()).digest()):
            raise RequestError("口令不正确", 403)
        token = secrets.token_urlsafe(32)
        self.sessions[token] = wall.time() + 12 * 3600
        self._rotate()
        return token

    def logout(self, token):
        self.sessions.pop(token, None)
        self._rotate()

    @contextmanager
    def _writer(self):
        if not self.ledger_path.exists():
            raise RequestError("正式台账不存在。请先运行 python -m src.ledger init --db <路径>", 503)
        ledger = Ledger(self.ledger_path, clock=lambda: self.clock, replay=True) if self.clock else Ledger(self.ledger_path)
        try:
            yield ledger
        finally:
            ledger.close()

    def quote(self, theme_id, mode=None):
        found = next((item for item in panel_containers() if item["theme_id"] == theme_id), None)
        if found is None:
            raise RequestError("未知容器")
        observed = self.observation(mode, theme=theme_id, series="execution", weeks=1)
        fields = (observed.get("detail") or {}).get("fields") or {}
        close = (fields.get("close") or {}).get("value")
        atr = (fields.get("atr20") or {}).get("value")
        state = (fields.get("state") or {}).get("value")
        rank = (fields.get("rank") or {}).get("value")
        if not _finite(close) or not _finite(atr) or atr <= 0:
            raise RequestError("该执行 ETF 的最近收盘或 ATR20 不可用")
        return {"theme_id": theme_id, "container": found["container"], "code": found["code"], "name": found["name"],
                "close": close, "atr20": atr, "suggested": round(close - 2 * atr, 6), "state": state,
                "rank": rank, "close_date": observed.get("effective_date"),
                "reason": (fields.get("atr20") or {}).get("reason")}

    def _create(self, body):
        self._check_revision(body)
        if not isinstance(body, dict):
            raise RequestError("请求含不允许的字段；冻结字段不可修改")
        theme = body.get("theme_id")
        instrument = next((item for item in panel_containers() if item["theme_id"] == theme), None)
        if instrument is None:
            raise RequestError("未知容器")
        try:
            quote = self.quote(theme, "readonly")
            if not quote["close_date"]:
                raise FormError("当前没有已完成的交易日，不能立卡")
            trading = _trading_days(self.market_path)
            deadline = next_weekday_open(quote["close_date"], trading)
            grades = source_grades()
            hs300 = _benchmark_close(self.market_path, quote["close_date"])
        except FormError as exc:
            raise RequestError(str(exc)) from exc
        if hs300 is None:
            raise RequestError("创建日没有 H00300 收盘，不能立卡")
        try:
            payload = {key: value for key, value in body.items() if key != "revision"}
            with self._writer() as ledger:
                level = _ew_level(ledger, quote["close_date"])
                card, evidence = assemble(payload, quote=quote, now=ledger.now(), deadline=deadline, ew_level=level,
                                          hs300=hs300, instrument=instrument, grades=grades)
                if body.get("supersedes"):
                    ledger.void(body["supersedes"], str(body.get("void_reason")).strip())
                return ledger.create_card(card, evidence, None)
        except FormError as exc:
            raise RequestError(str(exc)) from exc


def _minute(value):
    try:
        return bool(value) and datetime.strptime(value, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%dT%H:%M") == value
    except (TypeError, ValueError):
        return False


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) < 1e15


def _trading_days(path):
    if not path.exists():
        return None
    con = MarketDB.connect(path, readonly=True)
    try:
        return load_trading_days(con)
    finally:
        con.close()


def _benchmark_close(path, day):
    if not path.exists():
        return None
    con = MarketDB.connect(path, readonly=True)
    try:
        row = con.execute("SELECT close FROM bars WHERE code=? AND adj='raw' AND date=? AND close > 0 ORDER BY source LIMIT 1",
                          (BENCH_CODE, day)).fetchone()
        return float(row[0]) if row and row[0] == row[0] else None
    finally:
        con.close()


def _ew_level(ledger, day):
    rows = ledger.ew_rows()
    if day in rows:
        return rows[day][1]
    if rows and day < max(rows):
        raise FormError("等权日收益已记到更晚的日期，不能补记这张卡的创建日")
    if not rows:
        ledger.record_ew(day, 0.0, 1.0, 1)
        return 1.0
    previous = rows[max(rows)][1]
    ledger.record_ew(day, 0.0, previous, 1)
    return previous
