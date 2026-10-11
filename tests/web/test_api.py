"""实际本机 HTTP 接口：双盲、领域交互、只读隔离与请求边界。"""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data import db as MarketDB
from src.ledger.store import ROOT, Ledger
from src.web.application import Application, RequestError, read_ledger
from src.web.server import create_server, validate_binding
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

    def start_server(self, app, **kwargs):
        server = create_server(app, port=0, **kwargs)
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
        self.assertTrue(state["readonly_available"])
        self.assertEqual({c["status"] for c in state["cards"]}, {"候选", "当下", "过去", "已结", "作废"})
        holding = next(c for c in state["cards"] if c["status"] == "当下")
        self.assertGreater(holding["daily_date"], holding["close_date"])
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

    def test_public_demo_host_is_exact_same_origin_and_formal_reads_are_blocked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            with patch("src.web.application.load_rule_config", side_effect=AssertionError("正式规则读取")), \
                 patch("src.web.application.preflight", side_effect=AssertionError("正式行情读取")), \
                 patch.object(Application, "data_status", side_effect=AssertionError("正式状态读取")), \
                 patch("src.web.application.read_ledger", wraps=read_ledger) as reader:
                app = Application(directory, demo_only=True, ledger_path=self.formal, market_path=self.market)
                server = self.start_server(app, host="0.0.0.0", public_host="111.19.137.226")
                host = f"111.19.137.226:{server.server_port}"
                status, state = self.request("GET", "/api/state", headers={"Host": host}, server=server)
                self.assertEqual(status, 200, state)
                self.assertTrue(state["writable"])
                self.assertFalse(state["readonly_available"])
                self.assertEqual(state["rules"]["enabled"], ["事件驱动"])
                self.assertEqual(state["rules"]["blocked"], [])
                self.assertIn("纯演示", state["data_status"]["note"])
                for forbidden in ("unknown.example", "111.19.137.227", "111.19.137.226",
                                  f"111.19.137.226:{server.server_port + 1}"):
                    self.assertEqual(self.request("GET", "/api/state", headers={"Host": forbidden}, server=server)[0], 403)
                self.assertEqual(self.request("GET", "/api/state", headers={"Host": f"localhost:{server.server_port}"}, server=server)[0], 200)
                self.assertEqual(self.post("/api/demo/advance", state=state, server=server,
                    headers={"Host": host, "Origin": "http://unknown.example"})[0], 403)
                self.assertEqual(self.post("/api/demo/advance", state=state, server=server,
                    headers={"Host": host, "Origin": f"http://127.0.0.1:{server.server_port}"})[0], 403)
                self.assertEqual(self.post("/api/demo/advance", state=state, server=server,
                    headers={"Host": host, "Origin": f"http://{host}", "X-CSRF-Token": "wrong"})[0], 403)
                self.assertEqual(self.post("/api/cards/T-2026-005/score", {"score": 1, "reason": "远程合成演示"},
                    state=state, server=server, headers={"Host": host, "Origin": f"http://{host}"})[0], 200)
                self.assertEqual(self.post("/api/demo/advance", server=server,
                    headers={"Host": host, "Origin": f"http://{host}"})[0], 200)
                for path in ("/?mode=readonly", "/api/state?mode=readonly", "/api/cards/T-2026-005?mode=readonly"):
                    self.assertEqual(self.request("GET", path, headers={"Host": host}, server=server)[0], 403)
                self.assertEqual(self.post("/api/demo/reset?mode=readonly", server=server, headers={"Host": host})[0], 403)
                for call in (lambda: app.state("readonly"), lambda: app.detail("T-2026-005", "readonly"),
                             lambda: app.mutate("reset", {}, mode="readonly"), lambda: app._reader("readonly")):
                    with self.assertRaises(RequestError) as error:
                        call()
                    self.assertEqual(error.exception.status, 403)
                self.assertTrue(reader.called)
                self.assertTrue(all(call.args[0] == app.demo.path and call.kwargs["replay"] for call in reader.call_args_list))
        self.assertFalse(self.formal.exists())
        self.assertFalse(self.market.exists())

    def test_remote_binding_requires_explicit_demo_only_and_literal_public_host(self):
        with patch("src.web.server.ThreadingHTTPServer") as http_server:
            for host, public in (("0.0.0.0", None), ("0.0.0.0", "111.19.137.226"),
                                 ("111.19.137.226", "111.19.137.226"), ("127.0.0.1", "111.19.137.226")):
                with self.assertRaises(ValueError):
                    create_server(self.app, host=host, public_host=public)
            readonly = Application(mode="readonly", ledger_path=self.formal, market_path=self.market)
            with self.assertRaises(ValueError):
                create_server(readonly, host="0.0.0.0", public_host="111.19.137.226")
            for public in ("*", "0.0.0.0", "127.0.0.1", "localhost", "111.19.137.226:8765", "224.0.0.1"):
                with self.assertRaises(ValueError):
                    validate_binding("0.0.0.0", public, True)
            http_server.assert_not_called()
        with self.assertRaises(ValueError):
            Application(self.directory / "outside-outputs", demo_only=True)
        with self.assertRaises(ValueError):
            Application(mode="readonly", demo_only=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            app = Application(directory, demo_only=True)
            with self.assertRaises(RequestError):
                app.data_status()

    def test_cli_rejects_unsafe_remote_options_before_application_initialization(self):
        from src.web.__main__ import main
        for args in (("--host", "0.0.0.0"),
                     ("--host", "0.0.0.0", "--public-host", "111.19.137.226"),
                     ("--host", "0.0.0.0", "--demo-only"),
                     ("--host", "0.0.0.0", "--public-host", "111.19.137.226", "--mode", "readonly")):
            with self.subTest(args=args), patch("sys.argv", ["src.web", *args]), \
                 patch("sys.stderr"), patch("src.web.__main__.Application") as application:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                application.assert_not_called()
        with patch("sys.argv", ["src.web", "--demo-only", "--mode", "readonly"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)

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


class MarketHttpTests(unittest.TestCase):
    start_server = HttpTests.start_server
    request = HttpTests.request
    state = HttpTests.state

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.market = self.directory / "market.sqlite"
        self.formal = self.directory / "ledger.sqlite"
        self.formal.write_bytes(b"private ledger sentinel")
        self.demo_dir = self.directory / "unused-demo"
        con = MarketDB.connect(self.market)
        with con:
            con.execute("INSERT INTO runs(kind,started_at,args,status) VALUES ('backfill','2026-10-01','private args /secret/path?token=secret','ok')")
            for code, adj, source in (("H00852", "raw", "csi"), ("H00905", "raw", "csi"),
                                      ("000852", "raw", "tencent_price_index_offline"),
                                      ("000905", "raw", "tencent_price_index_offline"),
                                      ("512100", "raw", "tencent_etf"), ("512100", "hfq", "eastmoney_etf_hfq"),
                                      ("UNREGISTERED", "raw", "csi")):
                for day, close in (("2026-09-29", 14.0), ("2026-09-30", 9.0)):
                    con.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (code, adj, day, None if day.endswith("29") else 8.0, 15.0, 7.0,
                                 None if code == "UNREGISTERED" and day.endswith("30") else close,
                                 None, None if source == "csi" else 100.0, source, "2026-10-01T00:00:00Z"))
        MarketDB.write_coverage(con, 1, [
            {"theme_id": "T01", "container": "中证1000", "code": "000852", "series_code": "H00852",
             "series_adj": "raw", "route_used": "csi", "series_name": "中证1000全收益指数", "tr_code_used": "H00852",
             "price_only": False, "exec_code": "512100", "exec_route": "tencent_etf", "status": "retained"},
            {"theme_id": "T02", "container": "中证500", "code": "000905", "series_code": "H00905",
             "series_adj": "raw", "route_used": "csi", "series_name": "中证500全收益指数", "tr_code_used": "H00905",
             "price_only": False, "status": "retained"}])
        con.close()
        for target in ("src.web.application.DemoStore", "src.web.application.read_ledger",
                       "src.web.application.load_rule_config", "src.web.application.preflight",
                       "src.web.application.Application.data_status", "src.ledger.store.Ledger"):
            patcher = patch(target, side_effect=AssertionError("行情预览禁止调用 " + target))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = Application(self.demo_dir, mode="market", market_path=self.market, ledger_path=self.formal)
        self.server = self.start_server(self.app, host="0.0.0.0", public_host="111.19.137.226")

    def digest(self):
        return hashlib.sha256(self.market.read_bytes()).hexdigest()

    def test_snapshot_latest_null_counts_registered_names_and_original_hash(self):
        before = self.digest()
        formal_before = self.formal.read_bytes()
        state = self.state()
        self.assertEqual(state["mode"], "market")
        self.assertFalse(state["writable"])
        self.assertFalse(state["demo_available"])
        self.assertIsNone(self.app.csrf_token)
        self.assertEqual(state["cards"], [])
        self.assertNotIn("csrf_token", state)
        self.assertNotIn("rules", state)
        self.assertEqual(state["ledger_note"], "此观察入口不载入正式判断/扫描结果。")
        self.assertEqual(state["observation_as_of"], "2026-09-30")
        market = state["market"]
        self.assertEqual(market["rows"], 14)
        self.assertEqual((market["first"], market["last"]), ("2026-09-29", "2026-09-30"))
        series = {(r["code"], r["adj"]): r for r in market["series"]}
        self.assertEqual(len(series), 7)
        row = series["H00852", "raw"]
        self.assertEqual(row["close"], 9.0)  # 最新日期，不是 max(close)。
        self.assertEqual(row["source"], "csi")
        self.assertEqual(row["name"], "中证1000全收益指数")
        self.assertEqual(row["containers"], ["中证1000"])
        self.assertEqual(row["type"], "全收益指数")
        self.assertTrue(row["research_selected"])
        self.assertFalse(row["price_only"])
        self.assertEqual((row["ohlc_null"], row["open_null"], row["high_null"], row["low_null"], row["close_null"]), (1, 1, 0, 0, 0))
        self.assertEqual((row["volume_null"], row["amount_null"]), (2, 2))
        for code in ("000852", "000905"):
            self.assertTrue(series[code, "raw"]["price_only"])
            self.assertFalse(series[code, "raw"]["research_selected"])
            self.assertEqual(series[code, "raw"]["name"], code)
            self.assertEqual(series[code, "raw"]["type"], "价格指数")
        self.assertEqual(series["512100", "raw"]["type"], "ETF · 不复权")
        self.assertEqual(series["512100", "hfq"]["type"], "ETF · 含分红后复权")
        self.assertEqual(series["UNREGISTERED", "raw"]["name"], "UNREGISTERED")
        self.assertEqual(series["UNREGISTERED", "raw"]["containers"], [])
        self.assertIsNone(series["UNREGISTERED", "raw"]["close"])
        public = json.dumps(state)
        for private in ("private", "secret", str(self.directory), "positions", "runs", "agent_strength"):
            self.assertNotIn(private, public)
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.formal.read_bytes(), formal_before)
        self.assertFalse(self.demo_dir.exists())
        self.assertFalse(Path(str(self.market) + "-journal").exists())
        self.assertFalse(Path(str(self.market) + "-wal").exists())
        # 合法写入者发布新行情后，下一个请求读取新快照；web 本身从不写入。
        con = MarketDB.connect(self.market)
        with con:
            con.execute("INSERT INTO bars VALUES ('H00852','raw','2026-10-01',8,10,7,8.5,NULL,NULL,'csi','2026-10-01T10:00:00Z')")
        con.close()
        updated_hash = self.digest()
        updated = self.state()["market"]
        self.assertEqual(updated["last"], "2026-10-01")
        self.assertEqual(updated["rows"], 15)
        self.assertEqual(next(r for r in updated["series"] if r["code"] == "H00852")["close"], 8.5)
        self.assertEqual(self.digest(), updated_hash)

    def test_all_posts_modes_card_access_and_direct_methods_are_rejected(self):
        host = f"111.19.137.226:{self.server.server_port}"
        self.assertEqual(self.request("GET", "/api/state?mode=market", headers={"Host": host})[0], 200)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "unknown.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": host, "Origin": "https://other.example"})[0], 403)
        before = self.digest()
        for mode in ("demo", "readonly"):
            for path in (f"/?mode={mode}", f"/api/state?mode={mode}", f"/api/cards/T-2026-005?mode={mode}"):
                self.assertEqual(self.request("GET", path)[0], 403)
        for path in ("/api/demo/reset", "/api/demo/advance", "/api/cards/T-2026-005/score", "/api/state", "/anything"):
            self.assertEqual(self.request("POST", path, {"revision": None},
                {"Host": host, "Origin": f"http://{host}", "Content-Type": "application/json", "X-CSRF-Token": "fake"})[0], 403)
        self.assertEqual(self.request("GET", "/api/cards/T-2026-005")[0], 403)
        for mode in (None, "market", "demo", "readonly"):
            for call in (lambda: self.app.detail("T-2026-005", mode),
                         lambda: self.app.mutate("reset", {}, mode=mode), lambda: self.app._reader(mode)):
                with self.assertRaises(RequestError) as error:
                    call()
                self.assertEqual(error.exception.status, 403)
        for mode in ("demo", "readonly"):
            with self.assertRaises(RequestError):
                self.app.state(mode)
        self.assertEqual(self.digest(), before)
        self.assertFalse(self.demo_dir.exists())

    def test_unknown_market_schema_is_refused_without_migration_or_path_leak(self):
        con = MarketDB.connect(self.market)
        with con:
            con.execute("UPDATE meta SET value='old-market' WHERE key='schema'")
        con.close()
        before = self.digest()
        status, payload = self.request("GET", "/api/state")
        self.assertEqual(status, 503)
        self.assertNotIn(str(self.market), json.dumps(payload))
        self.assertEqual(self.digest(), before)

    def test_missing_market_and_ledger_stay_missing(self):
        missing = self.directory / "missing" / "market.sqlite"
        self.formal.unlink()
        app = Application(self.demo_dir, mode="market", market_path=missing, ledger_path=self.formal)
        server = self.start_server(app)
        state = self.state(server)
        self.assertFalse(state["market"]["available"])
        self.assertEqual(state["market"]["series"], [])
        self.assertIsNone(state["observation_as_of"])
        self.assertFalse(missing.parent.exists())
        self.assertFalse(self.formal.exists())
        self.assertFalse(self.demo_dir.exists())
        with self.assertRaises(ValueError):
            Application(mode="market", demo_only=True)
        with self.assertRaises(ValueError):
            validate_binding("0.0.0.0", None, False, mode="market")


if __name__ == "__main__":
    unittest.main()
