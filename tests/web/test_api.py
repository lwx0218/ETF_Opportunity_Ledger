"""实际本机 HTTP 接口：双盲、领域交互、只读隔离与请求边界。"""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ledger.store import Ledger
from src.web.application import Application
from src.web.server import create_server
from tests.ledger.test_ledger import T0, card


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.formal = self.directory / "formal" / "ledger.sqlite"
        self.market = self.directory / "formal" / "market.sqlite"
        self.app = Application(self.directory / "demo", ledger_path=self.formal, market_path=self.market)
        self.server = self.start_server(self.app)

    def start_server(self, app):
        server = create_server(app, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.addCleanup(stop)
        return server

    def request(self, method, path, body=None, headers=None, server=None):
        server = server or self.server
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            raw = response.read()
            payload = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
            return response.status, payload
        finally:
            conn.close()

    def state(self, server=None, path="/api/state"):
        status, payload = self.request("GET", path, server=server)
        self.assertEqual(status, 200, payload)
        return payload

    def post(self, path, body=None, *, state=None, headers=None, server=None):
        state = state or self.state(server)
        payload = {"revision": state["revision"], **(body or {})}
        return self.request("POST", path, payload,
                            {"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"], **(headers or {})}, server)

    def assert_blind(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                self.assertNotIn(key, {"agent_strength", "agent_score", "agent_reason", "agent_scores"})
                if key == "agent":
                    self.assertIn(item, (None, {
                        "status": "held_until_review",
                        "reason": "Owner 入口不披露 agent 个体评分或分桶，避免双盲信息泄露。",
                    }))
                if key == "rater":
                    self.assertNotEqual(item, "agent")
                self.assert_blind(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_blind(item)

    def test_state_and_all_details_never_return_agent_score_or_reason(self):
        state = self.state()
        self.assertEqual(state["summary"]["denominator"], 6)
        self.assertTrue(state["demo_available"])
        self.assertEqual({c["status"] for c in state["cards"]}, {"候选", "当下", "过去", "已结", "作废"})
        self.assert_blind(state)
        with self.app.demo.open_ledger() as ledger:
            reasons = [r[0] for r in ledger.conn.execute("SELECT reason FROM strength_scores WHERE rater='agent'")]
        for candidate in state["cards"]:
            status, detail = self.request("GET", f"/api/cards/{candidate['id']}")
            self.assertEqual(status, 200)
            self.assertIsNone(detail["scores"]["agent"])
            self.assert_blind(detail)
            for secret in reasons:
                self.assertNotIn(secret, json.dumps(detail, ensure_ascii=False))
        status, updated = self.post("/api/cards/T-2026-005/score", {"score": 1, "reason": "独立判断，没有证据"})
        self.assertEqual(status, 200, updated)
        self.assert_blind(updated)
        status, detail = self.request("GET", "/api/cards/T-2026-005")
        self.assertEqual(status, 200)
        self.assertEqual(detail["scores"]["owner"]["score"], 1)
        self.assertIsNone(detail["scores"]["agent"])
        self.assert_blind(detail)
        self.assertFalse(detail["actions"]["can_score"])

    def test_score_validation_duplicate_deadline_and_stale_revision(self):
        initial = self.state()
        for score in (True, "2", -1, 6, 2.5):
            with self.subTest(score=score):
                status, _ = self.post("/api/cards/T-2026-005/score", {"score": score, "reason": "评分必须是整数"})
                self.assertEqual(status, 400)
        self.assertEqual(self.post("/api/cards/T-2026-005/score", {"score": 1, "reason": "独立判断"})[0], 200)
        self.assertEqual(self.post("/api/cards/T-2026-005/score", {"score": 1, "reason": "重复判断"})[0], 409)
        self.assertEqual(self.post("/api/cards/T-2026-006/void", {"reason": "旧页面"}, state=initial)[0], 409)
        self.assertEqual(self.post("/api/demo/advance")[0], 200)
        status, detail = self.request("GET", "/api/cards/T-2026-006")
        self.assertEqual(status, 200)
        self.assertFalse(detail["actions"]["can_score"])
        self.assertEqual(self.post("/api/cards/T-2026-006/score", {"score": 1, "reason": "已经过期"})[0], 409)

    def test_void_stays_in_denominator_and_signal_fills_only_after_advance(self):
        status, after_void = self.post("/api/cards/T-2026-006/void", {"reason": "撤销候选，保留记录"})
        self.assertEqual(status, 200, after_void)
        self.assertEqual(after_void["summary"]["denominator"], 6)
        self.assertEqual(after_void["summary"]["by_status"]["作废"], 2)
        for path, body in (("/api/cards/T-2026-004/void", {"reason": "持仓不能作废"}),
                           ("/api/cards/T-2026-005/exit-signal", {"reason": "论点作废"}),
                           ("/api/cards/T-2026-004/exit-signal", {"reason": "跟踪期满"}),
                           ("/api/cards/T-2026-004/exit-signal", {"reason": "手动"})):
            self.assertIn(self.post(path, body)[0], (400, 409))
        status, _ = self.post("/api/cards/T-2026-004/exit-signal", {"reason": "手动", "manual_reason": "演示主动离场"})
        self.assertEqual(status, 200)
        _, detail = self.request("GET", "/api/cards/T-2026-004")
        self.assertEqual(detail["status"], "当下")
        self.assertIsNone(detail["exit"])
        self.assertEqual(len(detail["signals"]), 1)
        signal_date = detail["signals"][0]["signal_date"]
        self.assertEqual(self.post("/api/demo/advance")[0], 200)
        _, detail = self.request("GET", "/api/cards/T-2026-004")
        self.assertEqual(detail["status"], "过去")
        self.assertGreater(detail["exit"]["exit_date"], signal_date)
        self.assertEqual(detail["exit"]["exit_reason"], "手动")
        self.assertEqual(self.state()["summary"]["denominator"], 6)

    def test_score_at_the_exact_deadline_is_rejected(self):
        _, detail = self.request("GET", "/api/cards/T-2026-005")
        before = self.app.demo.path.read_bytes()
        with patch.object(self.app.demo, "now", return_value=detail["actions"]["score_deadline"]):
            _, at_deadline = self.request("GET", "/api/cards/T-2026-005")
            self.assertFalse(at_deadline["actions"]["can_score"])
            status, _ = self.post("/api/cards/T-2026-005/score", {"score": 1, "reason": "正好截止时仍应拒绝"})
            self.assertEqual(status, 409)
        self.assertEqual(self.app.demo.path.read_bytes(), before)

    def test_frozen_fields_and_arbitrary_paths_cannot_be_submitted(self):
        before = self.app.demo.path.read_bytes()
        for field in ("thesis", "invalidation_price", "expectation_target_excess_pct", "evidence", "db", "path", "scored_at"):
            status, _ = self.post("/api/cards/T-2026-005/score", {"score": 2, "reason": "测试", field: "forbidden"})
            self.assertEqual(status, 400, field)
        for path in ("/api/state?db=/tmp/anything.sqlite", "/api/state?mode=demo&mode=readonly",
                     "/api/cards/T-2026-005?path=/tmp/anything.sqlite", "/api/state?mode=other"):
            self.assertEqual(self.request("GET", path)[0], 400, path)
        self.assertEqual(self.request("GET", "/../application.py")[0], 404)
        self.assertEqual(self.request("GET", "/api/cards/T-2026-999")[0], 404)
        self.assertEqual(self.app.demo.path.read_bytes(), before)

    def test_csrf_origin_host_and_json_request_boundaries(self):
        state = self.state()
        before = self.app.demo.path.read_bytes()
        self.assertEqual(self.post("/api/demo/advance", state=state, headers={"X-CSRF-Token": "wrong"})[0], 403)
        self.assertEqual(self.post("/api/demo/advance", state=state, headers={"Origin": "https://untrusted.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "untrusted.example"})[0], 403)
        self.assertEqual(self.post("/api/demo/advance", state=state, headers={"Content-Type": "text/plain"})[0], 415)
        headers = {"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]}
        self.assertEqual(self.request("POST", "/api/demo/advance", b"{}", {"Content-Type": "application/json"})[0], 403)
        for body in (b"{", b"\xff", b"null", b"[]"):
            self.assertEqual(self.request("POST", "/api/demo/advance", body, headers)[0], 400)
        for extra in ({"Content-Length": "0"}, {"Content-Length": "-1"}, {"Content-Length": "16385"},
                      {"Transfer-Encoding": "chunked"}):
            self.assertEqual(self.request("POST", "/api/demo/advance", b"{}", headers | extra)[0], 413)
        self.assertEqual(self.app.demo.path.read_bytes(), before)
        payload = json.dumps({"revision": state["revision"]}).encode().ljust(16384, b" ")
        allowed = headers | {"Origin": f"http://127.0.0.1:{self.server.server_port}"}
        self.assertEqual(self.request("POST", "/api/demo/advance", payload, allowed)[0], 200)

    def test_missing_formal_mode_never_creates_files_and_rejects_writes(self):
        state = self.state(path="/api/state?mode=readonly")
        self.assertFalse(state["writable"])
        self.assertEqual(state["cards"], [])
        self.assertEqual(self.post("/api/demo/reset?mode=readonly", state=state)[0], 403)
        app = Application(self.directory / "unused-demo", mode="readonly", ledger_path=self.formal, market_path=self.market)
        server = self.start_server(app)
        readonly = self.state(server)
        self.assertFalse(readonly["writable"])
        self.assertFalse(readonly["demo_available"])
        self.assertEqual(self.request("GET", "/api/state?mode=demo", server=server)[0], 403)
        self.assertEqual(self.post("/api/demo/advance", server=server)[0], 403)
        self.assertFalse(self.formal.exists())
        self.assertFalse(self.market.exists())
        self.assertFalse((self.directory / "unused-demo").exists())

    def test_existing_formal_fixture_is_readonly_and_hash_preserved(self):
        # Only the temporary fixture uses a mocked real clock; the HTTP reader never constructs Ledger.
        with patch("src.ledger.store.beijing_now", return_value=T0) as clock:
            ledger = Ledger(self.formal)
            cid = ledger.create_card(card(evidence_status="已检索无证据"), [],
                                     {"score": 4, "reason": "不可披露的真实模式测试评分", "scored_at": T0})
            clock.return_value = "2026-10-12T16:00"
            ledger.enter(cid, "2026-10-12", 10.0, 6.25)
            ledger.append_daily(cid, {"date": "2026-10-12", "close": 10.2, "state": "TREND_UP",
                                      "r_current": 0.25, "stop_now": 9.2})
            ledger.close()
        before = self.formal.read_bytes()
        with patch("src.web.application.beijing_now", return_value="2026-10-13T16:00"):
            state = self.state(path="/api/state?mode=readonly")
            self.assertEqual(state["summary"]["denominator"], 1)
            self.assertEqual(state["as_of"], "2026-10-13T16:00")
            self.assertEqual(state["observation_as_of"], "2026-10-12")
            status, detail = self.request("GET", f"/api/cards/{cid}?mode=readonly")
            self.assertEqual(status, 200)
            self.assert_blind(state)
            self.assert_blind(detail)
            self.assertNotIn("不可披露的真实模式测试评分", json.dumps(detail, ensure_ascii=False))
            self.assertFalse(any(detail["actions"][key] for key in ("can_score", "can_void", "can_signal")))
            self.assertEqual(self.post(f"/api/cards/{cid}/score?mode=readonly", {"score": 1, "reason": "拒绝写入"}, state=state)[0], 403)
        self.assertEqual(self.formal.read_bytes(), before)
        self.assertFalse(self.market.exists())
        self.assertFalse(Path(str(self.formal) + "-journal").exists())
        self.assertFalse(Path(str(self.formal) + "-wal").exists())


if __name__ == "__main__":
    unittest.main()
