"""卡片详情把冻结证据逐条交出来，并把 events-snapshots/ 链到 archive/grok-raw。"""
import tempfile
import unittest
from pathlib import Path

from src.ledger.store import Ledger
from src.web.application import Application, snapshot_link
from tests.ledger.test_ledger import T0, card, ev


class EvidenceDetail(unittest.TestCase):
    def test_detail_names_the_source_and_links_grok_raw(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ledger.sqlite"
        sha = "ab" * 32
        ledger = Ledger(path, clock=lambda: T0, replay=True)
        ledger.create_card(
            card(container="地产", instrument_code="512200", instrument_name="南方中证全指房地产ETF",
                 thesis="房地产投资增速回升，统计局月报确认",
                 thesis_inval_source_id="CN-NBS-MONTHLY", thesis_inval_statement="下一期走弱即失效"),
            [ev(source_id="CN-NBS-MONTHLY", summary="全国房地产投资月报显示开发投资降幅收窄",
                url="https://www.stats.gov.cn/sj/zxfb/",
                snapshot_path="events-snapshots/2026-09-30/nbs realestate.txt", snapshot_sha256=sha),
             ev(source_id="CN-NBS-MONTHLY", summary="同一来源的另一条，快照不在 grok-raw",
                url="https://www.stats.gov.cn/sj/zxfb/",
                snapshot_path="snapshots/2026-09-30/local.txt", snapshot_sha256="cd" * 32,
                published_at="2026-10-08T22:31", available_at="2026-10-08T22:31", first_seen_at="2026-10-08T22:41")],
            dict(score=4, reason="统计局房地产投资数据，方向与论点一致", scored_at=T0))
        ledger.close()
        app = Application(mode="readonly", write=True, write_token="test-token-123456", clock=T0,
                          ledger_path=path, market_path=Path(tmp.name) / "market.sqlite")
        detail = app.detail("T-2026-001")
        first, second = detail["evidence"]
        self.assertEqual(first["source_id"], "CN-NBS-MONTHLY")
        self.assertEqual(first["source_grade"], "A")
        self.assertIn("房地产", first["source_name"])
        self.assertEqual(first["published_at"], "2026-10-08T22:30")
        self.assertEqual(first["snapshot_sha256"], sha)
        self.assertEqual(first["snapshot_url"], snapshot_link("events-snapshots/2026-09-30/nbs realestate.txt"))
        self.assertIn("/events-snapshots/2026-09-30/nbs%20realestate.txt", first["snapshot_url"])
        self.assertTrue(first["snapshot_url"].startswith(
            "https://github.com/lwx0218/ETF_Opportunity_Ledger/blob/archive/grok-raw/"))
        self.assertIsNone(second["snapshot_url"])
        self.assertEqual(detail["scores"]["agent"]["score"], 4)
        self.assertIn("统计局", detail["scores"]["agent"]["reason"])
