"""No real credentials/Discloud network needed."""
from pathlib import Path
import io
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import deploy_discloud as d


class DeploymentTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_discloud_uses_filename_for_multipart_form_field(self):
        # The official Discloud REST library appends files under file.name,
        # not under a generic 'file' form field.
        blob, mime = d.multipart(b"testzip")
        self.assertIn(b'name="jarvis-voice.zip"; filename="jarvis-voice.zip"', blob)
        self.assertIn(b"testzip", blob)
        self.assertTrue(mime.startswith("multipart/form-data; boundary="))

    def test_private_token_is_stable_separate(self):
        account = "test-discloud-token-example-32-plus-characters"
        one = d.private_token(account)
        self.assertEqual(one, d.private_token(account))
        self.assertNotEqual(one, account)
        self.assertGreaterEqual(len(one), 32)
        self.assertNotEqual(one, d.private_token(account + "new"))
        self.assertEqual(d.private_token(account, "q" * 48), "q" * 48)
        with self.assertRaises(ValueError):
            d.private_token(account, "weak")

    def test_only_exact_voice_app_can_be_updated(self):
        self.assertIsNone(d.app_id_for([{"name":"RivaL Intelligence","id":"rival"}]))
        self.assertEqual(d.app_id_for([{"name":"RivaL Intelligence","id":"rival"},
            {"name":"Jarvis-Voice","id":"voice1","mainFile":"server.py"}]), "voice1")
        with self.assertRaises(ValueError):
            d.app_id_for([{"name":"Jarvis-Voice","id":"rival","mainFile":"main.py"}])
        with self.assertRaises(ValueError):
            d.app_id_for([{"name":"Jarvis-Voice","id":"a","mainFile":"server.py"},
                          {"name":"Jarvis-Voice","id":"b","mainFile":"server.py"}])
        with self.assertRaises(ValueError):
            d.app_id_for([{"name":"Jarvis-Voice","id":"../x","mainFile":"server.py"}])

    def test_archive_only_contains_voice_runtime(self):
        token = "test-unique-private-voice-token-" + "x" * 20
        contents = d.package(self.root, token)
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            self.assertEqual(set(archive.namelist()), set(d.ARTIFACTS) | {".env"})
            env = archive.read(".env")
            self.assertIn(("JARVIS_VOICE_TOKEN=" + token).encode(), env)
            self.assertIn(b"JARVIS_CARTESIA_ENABLED=false", env)
            self.assertNotIn(b"RIVAL_LLM_SHARED_TOKEN", env)

    def test_no_new_app_when_exact_voice_exists(self):
        with patch.object(d, "api", side_effect=[
            {"status":"ok","apps":[{"name":"Jarvis-Voice","id":"voice-1","mainFile":"server.py"}]},
            {"status":"ok"}]) as api:
            actual = d.deploy(self.root, "t" * 48)
            self.assertEqual(actual, ("voice-1","updated"))
            self.assertEqual(api.call_args_list[1].args[1:3],
                             ("PUT", "/app/voice-1/commit"))

    def test_initial_creation_and_wrong_app_detection(self):
        with patch.object(d, "api", side_effect=[
            {"status":"ok","apps":[{"name":"RivaL Intelligence","id":"rival","mainFile":"main.py"}]},
            {"status":"ok","app":{"name":"Jarvis-Voice","id":"voice-new","mainFile":"server.py"}}]) as api:
            actual = d.deploy(self.root, "t" * 48)
            self.assertEqual(actual, ("voice-new","created"))
            self.assertEqual(api.call_args_list[1].args[1:3], ("POST", "/upload"))
        with patch.object(d, "api", return_value={"status":"ok","apps":[
            {"name":"Jarvis-Voice","id":"rival","mainFile":"main.py"}]}) as api:
            with self.assertRaises(ValueError):
                d.deploy(self.root, "t" * 48)
            self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
