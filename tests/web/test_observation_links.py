"""Reading links keep the series that produced the number."""
import subprocess
import unittest
from pathlib import Path


class ObservationLinkTests(unittest.TestCase):
    def test_reading_links_and_frozen_decision_lines(self):
        script = Path(__file__).with_name("test_observation_links.js")
        completed = subprocess.run(["node", str(script)], check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
