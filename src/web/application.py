"""HTTP 无关的薄应用层；不改冻结字段，不向浏览器投影 agent 个体评分。"""
from __future__ import annotations

import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from src.data.quality import preflight
from src.jobs.rules import ACTIVE_BEFORE_V1, load_rule_config
from src.ledger.read import summary
from src.ledger.store import CARD_FIELDS, DEFAULT_DB, ROOT, SCHEMA_VERSION, LedgerError, beijing_now
from src.scoring.review import counterfactual, review_report
from .demo import DemoStore


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


class Application:
    def __init__(self, demo_dir=ROOT / "outputs" / "app-demo", *, mode="demo",
                 ledger_path=DEFAULT_DB, market_path=ROOT / "data" / "market.sqlite"):
        if mode not in ("demo", "readonly"):
            raise ValueError("mode must be demo or readonly")
        self.mode = mode
        self.ledger_path, self.market_path = Path(ledger_path), Path(market_path)
        self.lock = threading.RLock()
        self.revision, self.csrf_token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        self.demo = DemoStore(demo_dir) if mode == "demo" else None
        if self.demo:
            for path in (self.ledger_path, self.market_path):
                if (path.resolve() == self.demo.path.resolve() or
                        (path.exists() and self.demo.path.exists() and path.samefile(self.demo.path))):
                    raise LedgerError("演示与正式路径不能重合")
            self.demo.ensure()
        self._data_cache = None

    def effective_mode(self, mode):
        if mode not in (None, "demo", "readonly"):
            raise RequestError("未知数据入口")
        if self.mode == "readonly" and mode == "demo":
            raise RequestError("此服务仅开放只读入口", 403)
        return mode or self.mode

    def _reader(self, mode):
        return read_ledger(self.demo.path if mode == "demo" else self.ledger_path, replay=mode == "demo")

    def data_status(self):
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
            now = self.demo.now() if mode == "demo" else beijing_now()
            cards = []
            observation_as_of = None
            review = None
            totals = {"denominator": 0, "terminal": 0, "by_status": {}, "by_final_score": {},
                      "hit_rate_over_terminal": None, "manual_exit_share": None}
            with self._reader(mode) as con:
                if con:
                    totals = summary(con)
                    review = review_report(con)
                    observation_as_of = con.execute("SELECT max(date) FROM daily").fetchone()[0]
                    cards = rows(con, """SELECT c.id,c.container,c.instrument_code,c.instrument_name,
                        s.status,c.thesis,c.trigger_type,c.created_at,c.close_date,c.owner_score_deadline,
                        c.thesis_inval_deadline AS next_observation,e.entry_date,x.exit_date,f.final_score,
                        (SELECT r_current FROM daily WHERE card_id=c.id ORDER BY date DESC LIMIT 1) AS r_current,
                        (SELECT close FROM daily WHERE card_id=c.id ORDER BY date DESC LIMIT 1) AS daily_close,
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
            enabled = list(load_rule_config(ROOT / "config" / "ledger-rules.json", problems))
            return {"mode": mode, "as_of": now, "observation_as_of": observation_as_of,
                    "demo_available": self.demo is not None, "writable": mode == "demo", "revision": self.revision,
                    "csrf_token": self.csrf_token, "cards": cards, "summary": totals, "review": review,
                    "rules": {"enabled": enabled, "blocked": [r for r in ACTIVE_BEFORE_V1 if r not in enabled] + ["形态突破"],
                              "note": "；".join(problems) or "正式规则配置仅供查看。演示推进使用独立合成输入。"},
                    "data_status": self.data_status()}

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
