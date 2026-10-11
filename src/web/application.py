"""HTTP 无关的薄应用层；不改冻结字段，不向浏览器投影 agent 个体评分。"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data import db as MarketDB
from src.data.quality import preflight
from src.data.universe import PANEL_STATUSES
from src.jobs.rules import ACTIVE_BEFORE_V1, load_rule_config
from src.ledger.read import summary
from src.ledger.store import CARD_FIELDS, DEFAULT_DB, ROOT, SCHEMA_VERSION, LedgerError, beijing_now
from src.scoring.review import counterfactual, review_report
from src.observation import observe
from .demo import DemoStore
from .demo_observation import demo_market


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
                 ledger_path=DEFAULT_DB, market_path=ROOT / "data" / "market.sqlite", demo_only=False):
        if mode not in ("demo", "readonly", "market"):
            raise ValueError("mode must be demo, readonly or market")
        if demo_only and mode != "demo":
            raise ValueError("纯演示服务只能使用 demo 模式")
        if demo_only and not Path(demo_dir).resolve().is_relative_to((ROOT / "outputs").resolve()):
            raise ValueError("纯演示目录必须位于 outputs 内")
        self.mode, self.demo_only = mode, demo_only
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
        return read_ledger(self.demo.path if mode == "demo" else self.ledger_path, replay=mode == "demo")

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

    def state(self, mode=None):
        with self.lock:
            mode = self.effective_mode(mode)
            if mode == "market":
                market = read_market(self.market_path)
                return {"mode": "market", "as_of": beijing_now(), "observation_as_of": market["last"],
                        "writable": False, "demo_available": False, "cards": [], "market": market,
                        "ledger_note": "此观察入口不载入正式判断/扫描结果。"}
            now = self.demo.now() if mode == "demo" else beijing_now()
            cards = []
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
                        EXISTS(SELECT 1 FROM strength_scores WHERE card_id=c.id AND rater='owner') AS owner_scored,
                        c.evidence_status
                        FROM cards c JOIN card_status s ON s.id=c.id
                        LEFT JOIN entries e ON e.card_id=c.id LEFT JOIN exits x ON x.card_id=c.id
                        LEFT JOIN finals f ON f.card_id=c.id WHERE c.sealed=1 ORDER BY c.created_at DESC,c.id DESC""")
            for card in cards:
                card["owner_score_status"] = ("已评分" if card.pop("owner_scored") else
                    "不适用" if card["evidence_status"] == "未检索" else
                    "已过期" if now >= card["owner_score_deadline"] else "待独立评分")
            problems = []
            enabled = ["事件驱动"] if mode == "demo" else list(load_rule_config(ROOT / "config" / "ledger-rules.json", problems))
            return {"mode": mode, "as_of": now, "observation_as_of": observation_as_of,
                    "demo_available": self.demo is not None, "readonly_available": self.mode != "market" and not self.demo_only,
                    "writable": mode == "demo", "revision": self.revision,
                    "csrf_token": self.csrf_token, "cards": cards, "summary": totals, "review": review,
                    "scan": {"latest_processed_day": latest_processed_day,
                             "note": "配置启用不表示已扫描；此处仅报告台账已处理日。"},
                    "rules": {"enabled": enabled, "blocked": [] if mode == "demo" else [r for r in ACTIVE_BEFORE_V1 if r not in enabled] + ["形态突破"],
                              "note": "纯演示：仅使用独立合成事件输入，不读取正式规则。" if mode == "demo" else
                                      "；".join(problems) or "正式规则配置仅供查看，不表示已执行扫描。"},
                    "data_status": {"benchmark_ready": False, "research_ready": False,
                                    "note": "纯演示：行情全部合成，不读取正式数据库。"} if mode == "demo" else self.data_status()}

    def observation(self, mode=None, *, as_of=None, theme=None, series="research", weeks=12):
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
            now = datetime.fromisoformat(self.demo.now() if mode == "demo" else beijing_now()).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
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

    def detail(self, card_id, mode=None):
        with self.lock:
            mode = self.effective_mode(mode)
            now = self.demo.now() if mode == "demo" else beijing_now()
            with self._reader(mode) as con:
                card = one(con, f"SELECT {','.join(CARD_FIELDS)} FROM cards WHERE id=? AND sealed=1", (card_id,)) if con else None
                if not card:
                    raise RequestError("未找到卡片", 404)
                status = con.execute("SELECT status FROM card_status WHERE id=?", (card_id,)).fetchone()[0]
                parts = {name: one(con, f"SELECT * FROM {table} WHERE card_id=?", (card_id,))
                         for name, table in (("entry", "entries"), ("exit", "exits"), ("final", "finals"), ("void", "voids"))}
                daily = rows(con, "SELECT * FROM daily WHERE card_id=? ORDER BY date", (card_id,))
                signals = rows(con, "SELECT * FROM exit_signals WHERE card_id=? ORDER BY seq", (card_id,))
                owner = one(con, "SELECT score,reason,scored_at FROM strength_scores WHERE card_id=? AND rater='owner'", (card_id,))
                evidence = rows(con, "SELECT * FROM evidence WHERE card_id=? ORDER BY seq", (card_id,))
                comparisons = counterfactual(con, card_id)
            completed = sum(d["date"] > parts["exit"]["exit_date"] for d in daily) if parts["exit"] else 0
            signal_date = daily[-1]["date"] if daily else None
            can_signal = status == "当下" and bool(daily) and (not signals or
                len(signals) == 1 and signals[0]["reason"] in ("失效位", "移动止盈") and signals[0]["signal_date"] == signal_date)
            return {"card": card, "status": status, **parts, "daily": daily, "evidence": evidence, "signals": signals,
                    "counterfactual": comparisons,
                    "scores": {"owner": owner, "agent": None, "agent_hidden": card["evidence_status"] != "未检索"},
                    "actions": {"can_score": mode == "demo" and owner is None and now < card["owner_score_deadline"] and card["evidence_status"] != "未检索",
                                "can_void": mode == "demo" and status == "候选",
                                "can_signal": mode == "demo" and can_signal,
                                "signal_date": signal_date, "score_deadline": card["owner_score_deadline"]},
                    "tracking": {"completed": completed, "required": card["tracking_days"]}}

    def mutate(self, action, body, *, card_id=None, mode=None):
        with self.lock:
            mode = self.effective_mode(mode)
            if mode != "demo":
                raise RequestError("正式入口只读", 403)
            fields = {"score": {"score", "reason"}, "void": {"reason"},
                      "exit-signal": {"reason", "manual_reason"}, "advance": set(), "reset": set()}
            if action not in fields:
                raise RequestError("未知操作", 404)
            if not isinstance(body, dict) or set(body) - (fields[action] | {"revision"}):
                raise RequestError("请求含不允许的字段；冻结字段不可修改")
            if body.get("revision") != self.revision:
                raise RequestError("页面已更新，请刷新后重试", 409)
            if action in ("advance", "reset"):
                getattr(self.demo, action)()
            else:
                detail = self.detail(card_id, mode)
                reason = body.get("reason")
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
                    raise RequestError("请填写理由（1–2000 字）")
                with self.demo.open_ledger() as ledger:
                    if action == "score":
                        score = body.get("score")
                        if type(score) is not int or not 0 <= score <= 5:
                            raise RequestError("评分须为 0–5 的整数")
                        ledger.owner_score(card_id, score, reason)
                    elif action == "void":
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
            self.revision = secrets.token_urlsafe(24)
            return self.state(mode)
