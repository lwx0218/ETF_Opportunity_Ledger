"""Observation routes keep page state and only read an isolated market snapshot."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.web.application import Application
from src.web.demo_observation import demo_market
from tests.web import test_api


class ObservationHttpTests(unittest.TestCase):
    start_server = test_api.HttpTests.start_server
    request = test_api.HttpTests.request

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.market = self.directory / "market.sqlite"
        with demo_market() as source:
            with sqlite3.connect(self.market) as target:
                source.backup(target)
        self.formal = self.directory / "ledger.sqlite"
        self.formal.write_bytes(b"private unreadable ledger sentinel")
        self.app = Application(mode="market", market_path=self.market, ledger_path=self.formal)
        self.server = self.start_server(self.app)
        clock = patch("src.web.application.beijing_now", return_value="2026-09-14T16:00")
        clock.start()
        self.addCleanup(clock.stop)

    def test_direct_page_query_and_observation_preserve_identity_and_files(self):
        before, private = self.market.read_bytes(), self.formal.read_bytes()
        with patch("src.web.application.read_ledger", side_effect=AssertionError("private")), \
             patch("src.web.application.load_rule_config", side_effect=AssertionError("rules")), \
             patch("src.web.application.DemoStore", side_effect=AssertionError("demo")):
            for path in ("/", "/rotation"):
                status, page = self.request("GET", path + "?mode=market&as_of=2026-09-14&theme=T02&series=execution")
                self.assertEqual(status, 200)
                self.assertIn(b"app.js", page)
            status, data = self.request("GET", "/api/observation?mode=market&as_of=2026-09-14&theme=T02&series=execution&weeks=1")
            self.assertEqual(status, 200, data)
            self.assertEqual(data["mode"], "market")
            self.assertEqual(data["effective_date"], "2026-09-14")
            self.assertEqual(len(data["containers"]), 37)
            self.assertEqual(data["detail"]["theme_id"], "T02")
            self.assertEqual(data["detail"]["series_kind"], "execution")
            self.assertEqual(data["detail"]["identity"]["purpose"], "execution")
            self.assertNotIn(str(self.directory), json.dumps(data))
            self.assertTrue(all(point["date"] <= "2026-09-14" for point in data["detail"]["chart"]))
        self.assertEqual(self.market.read_bytes(), before)
        self.assertEqual(self.formal.read_bytes(), private)
        self.assertFalse(Path(str(self.market) + "-journal").exists())
        self.assertFalse(Path(str(self.market) + "-wal").exists())

    def test_observation_routes_cannot_change_mode_or_accept_unsafe_parameters(self):
        for mode in ("demo", "readonly"):
            for path in ("/rotation", "/api/observation"):
                self.assertEqual(self.request("GET", f"{path}?mode={mode}")[0], 403)
        for query in ("db=/tmp/private", "as_of=2026-02-30", "as_of=20260914", "series=qfq",
                      "weeks=0", "weeks=27", "weeks=1.5", "theme=../", "theme=T99", "theme=T02&theme=T03",
                      "mode=market&mode=demo", "card=T-2026-005"):
            with self.subTest(query=query):
                self.assertEqual(self.request("GET", "/api/observation?" + query)[0], 400)
        self.assertEqual(self.request("POST", "/api/observation", {"as_of": "2026-09-14"})[0], 403)

    def test_future_and_uncovered_dates_remain_explicit_without_today_fallback(self):
        for day in ("2026-09-15", "1990-01-01"):
            status, result = self.request("GET", f"/api/observation?as_of={day}&weeks=1")
            self.assertEqual(status, 200, result)
            self.assertIsNone(result["effective_date"])
            self.assertTrue(result["reason"])
            self.assertEqual(result["containers"], [])

    def test_missing_or_old_market_is_not_created_or_migrated(self):
        missing = self.directory / "absent" / "market.sqlite"
        app = Application(mode="market", market_path=missing, ledger_path=self.formal)
        server = self.start_server(app)
        status, data = self.request("GET", "/api/observation", server=server)
        self.assertEqual(status, 503)
        self.assertIn("未创建", data["error"])
        self.assertFalse(missing.parent.exists())
        with sqlite3.connect(self.market) as con:
            con.execute("UPDATE meta SET value='old-market' WHERE key='schema'")
        before = self.market.read_bytes()
        self.assertEqual(self.request("GET", "/api/observation")[0], 503)
        self.assertEqual(self.market.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
