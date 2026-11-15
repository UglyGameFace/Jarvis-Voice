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
    def test_max_history_not_confused_with_all_time_peak(self):
        history=a.memory_receipt_summary(
            "memory_receipt current_mb=400 limit_mb=4088 oom_kills=0\n"
            "memory_receipt current_mb=1600 limit_mb=4088 oom_kills=0\n"
            "memory_receipt current_mb=700 limit_mb=4088 oom_kills=0\n")
        self.assertEqual(history["observations"],3)
        self.assertEqual(history["max_observed_current_mb"],1600)
        self.assertEqual(history["max_reported_oom_kills"],0)

    def test_unknown_apps_display_numeric_usage_without_names(self):
        report=a.summarize(
            {"totalRamMb":8192,"ramUsedMb":7650},
            [{"name":"unlisted-helper","ram":512,"online":True},
             {"name":"unlisted-minecraft","ram":256,"online":True}],
            {"unlisted-helper":{"memory":"98 MB"},
             "unlisted-minecraft":{"memory":"240 MB"}},
            None)
        result="\n".join(report)
        self.assertIn("Other #1: allocated=512MB online=True ramKilled=False instantaneous=98MB",result)
        self.assertIn("Other #2: allocated=256MB online=True ramKilled=False instantaneous=240MB",result)
        self.assertNotIn("unlisted-helper",result)
        self.assertNotIn("unlisted-minecraft",result)

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
        self.assertIn("Other #1: allocated=768MB online=False",out)
        self.assertNotIn("private-app-secret",out)


if __name__ == "__main__":
    unittest.main()
