"""No account credentials, network calls, or RAM changes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import audit_discloud_ram as a


class AuditTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(a.usage_mb("608 MB / 1.25 GB"), 608)
        self.assertEqual(a.usage_mb("0.5 GiB"), 512)
        self.assertIsNone(a.usage_mb("unavailable"))
    def test_receipt(self):
        x=a.latest_receipt("memory_receipt current_mb=200 peak_mb=300 oom_kills=0\n"
                           "memory_receipt current_mb=400 peak_mb=950 oom_kills=0\n")
        self.assertEqual(x, {"current_mb":400,"peak_mb":950,"oom_kills":0})
    def test_redacts_unknown_app_names(self):
        rows=a.summarize(
          {"totalRamMb":8192,"ramUsedMb":7650},
          [{"name":"RivaL","ram":1280,"online":True},
           {"name":"private-app-secret","ram":768,"online":False}],
          {"RivaL":{"memory":"608 MB","cpu":"20%"}},
          {"current_mb":800,"peak_mb":1200,"oom_kills":0})
        out="\n".join(rows)
        self.assertIn("free=542",out)
        self.assertIn("instantaneous=608MB",out)
        self.assertIn("count=1 allocated=768",out)
        self.assertNotIn("private-app-secret",out)


if __name__ == "__main__":
    unittest.main()
