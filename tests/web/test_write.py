"""正式台账的手动记账：口令、cookie、冻结字段拒绝，以及公网监听只放行 readonly + --write。"""
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ledger.store import ROOT
from src.web.application import Application
from src.web.server import create_server, validate_binding
from src.web.write_card import FormError, assemble, snapshot_sha256


TOKEN = "test-token-123456"


class WriteGate(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.formal = self.directory / "ledger.sqlite"
        self.market = self.directory / "market.sqlite"

    def test_write_without_token_refuses_startup(self):
        from src.web.__main__ import main
        with patch.dict(os.environ, {}, clear=False), patch("sys.argv", ["src.web", "--mode", "readonly", "--write"]), \
             patch("sys.stderr"), patch("src.web.__main__.Application") as application:
            os.environ.pop("LEDGER_WRITE_TOKEN", None)
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
            application.assert_not_called()
        with self.assertRaises(ValueError):
            Application(mode="readonly", write=True, write_token="short", ledger_path=self.formal, market_path=self.market)

    def test_public_bind_only_with_write(self):
        validate_binding("0.0.0.0", "111.19.137.226", False, mode="readonly", write=True)
        validate_binding("0.0.0.0", "111.19.137.226", False, mode="market", write=False)
        for kwargs in (dict(mode="readonly", write=False), dict(mode="demo", write=True)):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                validate_binding("0.0.0.0", "111.19.137.226", False, **kwargs)

    def test_readonly_without_write_stays_read_only(self):
        app = Application(mode="readonly", ledger_path=self.formal, market_path=self.market)
        status, _ = self.post(app, "/api/cards", {"thesis": "不能写"})
        self.assertEqual(status, 403)
        self.assertFalse(self.formal.exists())
        self.assertFalse(app.write)

    def test_login_cookie_and_frozen_field_rejected(self):
        app = Application(mode="readonly", write=True, write_token=TOKEN, ledger_path=self.formal, market_path=self.market)
        server = create_server(app, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(self.stop, server, thread)
        status, state = self.exchange(server, "GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertTrue(state["write_enabled"])
        self.assertFalse(state["authenticated"])
        self.assertFalse(state["writable"])
        denied, _ = self.exchange(server, "POST", "/api/cards", {"theme_id": "T30", "revision": state["revision"]},
                                  {"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]})
        self.assertEqual(denied, 403)
        logged, session, cookie = self.exchange(server, "POST", "/api/login",
                                               {"password": TOKEN, "revision": state["revision"]},
                                               {"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                                               cookie=True)
        self.assertEqual(logged, 200)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertTrue(session["authenticated"])
        self.assertTrue(session["writable"])
        self.assertIn("containers", session)
        blocked, body = self.exchange(server, "POST", "/api/cards/T-2026-001/score",
                                      {"score": 3, "reason": "独立判断", "thesis": "改冻结论点", "revision": session["revision"]},
                                      {"Content-Type": "application/json", "X-CSRF-Token": session["csrf_token"],
                                       "Cookie": cookie.split(";", 1)[0]})
        self.assertEqual(blocked, 400)
        self.assertIn("冻结字段不可修改", body["error"])
        self.assertFalse(self.formal.exists())

    def test_snapshot_hash_ignores_title_and_rejects_client_grade(self):
        excerpt = "库存下降"
        url = "https://www.eia.gov/petroleum/supply/weekly/"
        self.assertEqual(snapshot_sha256(url, excerpt), snapshot_sha256(url, excerpt))
        self.assertEqual(len(snapshot_sha256(url, excerpt)), 64)
        body = {"theme_id": "T30", "thesis": "库存下降", "evidence": [{
            "source_id": "ENE-EIA-WPSR", "url": url, "title": "标题", "published_at": "2026-09-24T10:00",
            "summary": excerpt, "available_at": "2026-09-24T10:00"}],
            "horizon_days": 20, "target_excess_pct": 3, "benchmark": "沪深300", "invalidation_price": 1.0,
            "thesis_inval_source_id": "ENE-EIA-WPSR", "thesis_inval_deadline": "2026-10-22",
            "thesis_inval_statement": "库存转增即失效", "planned_size_pct": 5}
        with self.assertRaises(FormError):
            assemble(body, quote={"close": 1.2, "atr20": 0.05, "state": "XB", "rank": 3, "close_date": "2026-09-24"},
                     now="2026-09-24T16:00", deadline="2026-09-28T09:30", ew_level=1.0, hs300=4000.0,
                     instrument={"theme_id": "T30", "container": "地产", "code": "512200", "name": "地产ETF",
                                 "research_index_code": "931775"},
                     grades={"ENE-EIA-WPSR": ("A", "EIA")})

    def exchange(self, server, method, path, body=None, headers=None, cookie=False):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        raw = json.dumps(body).encode() if body is not None else None
        try:
            conn.request(method, path, body=raw, headers=headers or {})
            response = conn.getresponse()
            payload = response.read()
            parsed = json.loads(payload) if response.getheader("Content-Type", "").startswith("application/json") else payload
            if cookie:
                return response.status, parsed, response.getheader("Set-Cookie")
            return response.status, parsed
        finally:
            conn.close()

    def post(self, app, path, body):
        server = create_server(app, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(self.stop, server, thread)
        status, state = self.exchange(server, "GET", "/api/state")
        self.assertEqual(status, 200, state)
        return self.exchange(server, "POST", path, {"revision": state["revision"], **body},
                             {"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]})

    @staticmethod
    def stop(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
