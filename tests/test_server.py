import contextlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

TOKEN = "test-private-jarvis-voice-token-should-never-leak-123"


class FakeEngine:
    ready = False
    def __init__(self):
        self.calls = []
    def speak(self, text, voice, speed):
        self.calls.append((text, voice, speed))
        return b"RIFFfake-kokoro-voice"


class VoiceUnitTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.premium_calls = []
        def premium(text, speed, key):
            self.premium_calls.append((text, speed, key))
            return b"RIFFfake-premium-voice"
        self.app = server.VoiceApp(server.Config(token=TOKEN), engine=self.engine, premium=premium)

    def test_default_voice_and_pacing(self):
        audio, provider = self.app.synthesize({"text": "  Good evening.  Sir! "})
        self.assertEqual(provider, "kokoro")
        self.assertEqual(audio, b"RIFFfake-kokoro-voice")
        self.assertEqual(self.engine.calls, [("Good evening. Sir!", "bm_george", .94)])
        self.assertEqual(self.premium_calls, [])

    def test_approved_british_voices_only(self):
        self.app.synthesize({"text": "Hello", "voice": "bm_fable", "speed": 1.02})
        self.app.synthesize({"text": "Hello", "voice": "bm_lewis"})
        for voice in ["af_heart", "custom_clone", None]:
            with self.subTest(voice=voice), self.assertRaises(ValueError):
                self.app.synthesize({"text": "Hello", "voice": voice})

    def test_reject_bad_text_and_unknown_fields(self):
        cases = [None, "", " ", "x"*481, "hello\x00", 5]
        for text in cases:
            with self.subTest(text=repr(text)[:30]), self.assertRaises(ValueError):
                self.app.synthesize({"text": text})
        with self.assertRaises(ValueError):
            self.app.synthesize({"text": "hello", "tools": []})
        self.assertEqual(self.engine.calls, [])

    def test_speed_bounds(self):
        for speed in [0.84, 1.11, "1.0", True, float("nan"), float("inf")]:
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                self.app.synthesize({"text": "Hi", "speed": speed})

    def test_premium_is_off_by_default(self):
        with self.assertRaises(PermissionError):
            self.app.synthesize({"text": "Hi", "provider": "clive"})
        self.assertFalse(self.premium_calls)
        self.assertFalse(self.engine.calls)

    def test_premium_requires_explicit_provider_even_when_enabled(self):
        self.app.config = server.Config(token=TOKEN, premium_enabled=True, cartesia_key="private")
        self.app.synthesize({"text": "A local test"})
        self.assertFalse(self.premium_calls)
        self.app.synthesize({"text": "Premium test", "provider": "clive"})
        self.assertEqual(self.premium_calls, [("Premium test", .94, "private")])

    def test_nonblocking_busy_and_safe_failure(self):
        self.app.lock.acquire()
        with self.assertRaises(BlockingIOError):
            self.app.synthesize({"text": "Hi"})
        self.app.lock.release()
        with patch.object(server, "rss_mb", return_value=900):
            self.app.config = server.Config(token=TOKEN, max_rss_mb=1000)
            with self.assertRaises(MemoryError):
                self.app.synthesize({"text": "Hi"})
        self.assertFalse(self.app.lock.locked())
        self.assertEqual(self.app.status()["errors"], 1)

    def test_env_needs_secret_and_valid_config(self):
        with patch.dict(os.environ, {"JARVIS_VOICE_TOKEN": "weak"}, clear=True):
            with self.assertRaises(ValueError):
                server.Config.from_env()
        with patch.dict(os.environ, {"JARVIS_VOICE_TOKEN": TOKEN, "JARVIS_CARTESIA_ENABLED":"true"}, clear=True):
            with self.assertRaises(ValueError):
                server.Config.from_env()
        with patch.dict(os.environ, {"JARVIS_VOICE_TOKEN": TOKEN, "JARVIS_CARTESIA_ENABLED":"true", "CARTESIA_API_KEY":"secret"}, clear=True):
            self.assertTrue(server.Config.from_env().premium_enabled)

    def test_discloud_private_dotenv_and_env_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text("JARVIS_VOICE_TOKEN=from-private-file-token-should-have-32-chars\n"
                                "JARVIS_VOICE_SPEED=1.03\nUNRELATED=value\n")
            with patch.dict(os.environ, {}, clear=True):
                server.load_private_dotenv(env_file)
                self.assertEqual(server.Config.from_env().default_speed, 1.03)
                self.assertNotIn("UNRELATED", os.environ)
            with patch.dict(os.environ, {"JARVIS_VOICE_TOKEN": TOKEN}, clear=True):
                server.load_private_dotenv(env_file)
                self.assertEqual(os.environ["JARVIS_VOICE_TOKEN"], TOKEN)
            other = Path(temp) / "linked.env"
            other.symlink_to(env_file)
            with self.assertRaises(ValueError):
                server.load_private_dotenv(other)

    def test_cartesia_payload_and_limits(self):
        seen = {}
        class Dummy:
            headers = {"Content-Length": "8"}
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, size):
                seen["limit"] = size
                return b"RIFFtest"
        def fake_open(request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            return Dummy()
        audio = server.cartesia_clive("Good morning", 1.0, "private-key", opener=fake_open)
        payload = json.loads(seen["request"].data)
        self.assertEqual(audio, b"RIFFtest")
        self.assertEqual(payload["voice"]["id"], server.CLIVE_ID)
        self.assertEqual(payload["locale"], "en-GB")
        self.assertEqual(seen["request"].get_header("X-api-key"), "private-key")
        self.assertEqual(seen["limit"], server.MAX_AUDIO_BYTES + 1)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = FakeEngine()
        cls.app = server.VoiceApp(server.Config(token=TOKEN), engine=cls.engine)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cls.app))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def req(self, path, payload=None, token=TOKEN, content_type="application/json"):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, dict(res.headers), res.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def test_auth_and_status(self):
        for bad in [None, "wrong"]:
            status, _, data = self.req("/v1/status", token=bad)
            self.assertEqual(status, 401)
            self.assertNotIn(TOKEN.encode(), data)
        status, headers, data = self.req("/v1/status")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(data)["model"], "hexgrad/Kokoro-82M")

    def test_audio_response_and_provider(self):
        status, headers, wav = self.req("/v1/speak", {"text": "Jarvis online."})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "audio/wav")
        self.assertEqual(headers["X-Jarvis-Voice-Provider"], "kokoro")
        self.assertTrue(wav.startswith(b"RIFF"))

    def test_disallowed_premium_and_errors(self):
        status, _, _ = self.req("/v1/speak", {"text": "Hello", "provider": "clive"})
        self.assertEqual(status, 403)
        status, _, _ = self.req("/v1/speak", {"text": ""})
        self.assertEqual(status, 400)
        status, _, _ = self.req("/not-found", {"text": "Hello"})
        self.assertEqual(status, 404)
        status, _, _ = self.req("/v1/speak", {"text": "Hi"}, token="wrong")
        self.assertEqual(status, 401)

    def test_busy_http(self):
        self.app.lock.acquire()
        try:
            status, _, _ = self.req("/v1/speak", {"text": "Hello"})
            self.assertEqual(status, 429)
        finally:
            self.app.lock.release()


if __name__ == "__main__":
    unittest.main()

class KokoroWaveTests(unittest.TestCase):
    def test_generates_valid_wav_with_sentence_pause(self):
        import numpy as np
        from types import SimpleNamespace
        import wave
        class Tensor:
            def detach(self): return self
            def cpu(self): return self
            def numpy(self): return np.array([0.1, 0.2, -0.2, -0.1], dtype=np.float32)
        class FakePipeline:
            def __init__(self): self.called = []
            def __call__(self, text, *, voice, speed):
                self.called.append((text, voice, speed))
                return iter([SimpleNamespace(audio=Tensor())])
        pipeline = FakePipeline()
        engine = server.KokoroEngine(cpu_threads=1)
        engine._pipeline = pipeline
        wav_bytes = engine.speak("Good evening. All systems ready!", "bm_george", 0.94)
        with wave.open(__import__('io').BytesIO(wav_bytes), 'rb') as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getnframes(), 8 + 24000 * server.SILENCE_MS // 1000)
        self.assertEqual([item[0] for item in pipeline.called], ["Good evening.", "All systems ready!"])
