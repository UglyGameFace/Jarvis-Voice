"""Private, CPU-only JARVIS text-to-speech service.

Runs on a separate Discloud application. It never imports or modifies the RivaL
LFM3 process, and no credentials or voice data are exposed to a browser.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import wave

SAMPLE_RATE = 24_000
ALLOWED_VOICES = ("bm_george", "bm_fable", "bm_lewis", "bm_daniel")
CLIVE_ID = "b24f41fd-00a3-4cd8-992a-a0c9f13f3ef1"
MAX_TEXT = 480
MAX_REQUEST_BYTES = 4096
MAX_AUDIO_BYTES = 4_000_000
SILENCE_MS = 130
LOG = logging.getLogger("jarvis-voice")


def positive_int(raw: str | None, default: int, *, low: int, high: int) -> int:
    value = default if not raw else int(raw)
    if not low <= value <= high:
        raise ValueError(f"integer configuration outside allowed range {low}..{high}")
    return value


# Discloud GitHub integration may create an .env file rather than exporting every
# variable to the process. Read only explicitly approved keys without eval/shell.
_DOTENV_KEYS = frozenset({
    "JARVIS_VOICE_TOKEN", "JARVIS_VOICE_HOST", "JARVIS_VOICE_PORT",
    "JARVIS_KOKORO_VOICE", "JARVIS_VOICE_SPEED", "JARVIS_VOICE_CPU_THREADS",
    "JARVIS_VOICE_MAX_RSS_MB", "JARVIS_CARTESIA_ENABLED", "CARTESIA_API_KEY",
})


def load_private_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("Private .env must be a small regular file, not a symlink")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in _DOTENV_KEYS and key not in os.environ:
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    token: str
    host: str = "0.0.0.0"
    port: int = 8777
    default_voice: str = "bm_george"
    default_speed: float = 0.94
    premium_enabled: bool = False
    cartesia_key: str = ""
    max_rss_mb: int = 0
    cpu_threads: int = 2

    @classmethod
    def from_env(cls) -> Config:
        load_private_dotenv()
        token = os.environ.get("JARVIS_VOICE_TOKEN", "")
        if len(token) < 32 or len(token) > 256:
            raise ValueError("JARVIS_VOICE_TOKEN must be a unique 32-256 character secret")
        voice = os.environ.get("JARVIS_KOKORO_VOICE", "bm_george")
        if voice not in ALLOWED_VOICES:
            raise ValueError("Unknown Kokoro voice")
        speed = float(os.environ.get("JARVIS_VOICE_SPEED", "0.94"))
        if not 0.85 <= speed <= 1.10:
            raise ValueError("JARVIS_VOICE_SPEED outside 0.85..1.10")
        premium = os.environ.get("JARVIS_CARTESIA_ENABLED", "false").lower() == "true"
        key = os.environ.get("CARTESIA_API_KEY", "")
        if premium and not key:
            raise ValueError("Premium voice enabled without a Cartesia key")
        return cls(
            token=token,
            host=os.environ.get("JARVIS_VOICE_HOST", "0.0.0.0"),
            port=positive_int(os.environ.get("JARVIS_VOICE_PORT"), 8777, low=1, high=65535),
            default_voice=voice,
            default_speed=speed,
            premium_enabled=premium,
            cartesia_key=key,
            max_rss_mb=positive_int(os.environ.get("JARVIS_VOICE_MAX_RSS_MB"), 0, low=0, high=131072),
            cpu_threads=positive_int(os.environ.get("JARVIS_VOICE_CPU_THREADS"), 2, low=1, high=8),
        )


def rss_mb() -> float | None:
    try:
        with open("/proc/self/status", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def safe_text(text: object) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError(f"text must be 1..{MAX_TEXT} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise ValueError("unsupported control characters")
    cleaned = re.sub(r"[ \t\n]+", " ", text).strip()
    return cleaned


def valid_speed(speed: object, default: float) -> float:
    if speed is None:
        return default
    if isinstance(speed, bool) or not isinstance(speed, (float, int)):
        raise ValueError("speed must be numeric")
    if not 0.85 <= float(speed) <= 1.10:
        raise ValueError("speed must be between 0.85 and 1.10")
    return float(speed)


class KokoroEngine:
    """One lazy-loaded Kokoro pipeline, shared by serialized CPU requests."""

    def __init__(self, cpu_threads: int):
        self._pipeline = None
        self._threads = cpu_threads

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def _load(self):
        if self._pipeline is None:
            # Never load on a status request. The model can need substantial RAM.
            import torch
            torch.set_num_threads(self._threads)
            from kokoro import KPipeline
            self._pipeline = KPipeline(lang_code="b", device="cpu")
        return self._pipeline

    def speak(self, text: str, voice: str, speed: float) -> bytes:
        import numpy as np
        pipeline = self._load()
        chunks: list[bytes] = []
        total = 0
        # Split at sentence boundaries to create a natural controlled pause.
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
        for index, sentence in enumerate(sentences):
            for result in pipeline(sentence, voice=voice, speed=speed):
                audio = result.audio
                if audio is None:
                    continue
                samples = np.clip(audio.detach().cpu().numpy(), -1.0, 1.0)
                pcm = (samples * 32767).astype("<i2").tobytes()
                total += len(pcm)
                if total > MAX_AUDIO_BYTES:
                    raise RuntimeError("Speech response exceeds bounded duration")
                chunks.append(pcm)
            if index < len(sentences) - 1:
                silence = b"\0\0" * (SAMPLE_RATE * SILENCE_MS // 1000)
                chunks.append(silence)
                total += len(silence)
        if not chunks:
            raise RuntimeError("Kokoro returned no audio")
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(b"".join(chunks))
        return output.getvalue()


def cartesia_clive(text: str, speed: float, api_key: str, opener=None) -> bytes:
    """Optional, explicitly chosen premium provider. Never called automatically."""
    payload = json.dumps({
        "model_id": "sonic-3.6", "transcript": text,
        "voice": {"id": CLIVE_ID}, "locale": "en-GB",
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE},
        "generation_config": {"speed": speed},
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.cartesia.ai/tts/bytes", data=payload, method="POST",
        headers={
            "X-API-Key": api_key,
            "Cartesia-Version": "2026-08-14",
            "Content-Type": "application/json",
        },
    )
    with (opener or urllib.request.urlopen)(request, timeout=25) as response:
        size = response.headers.get("Content-Length")
        if size is not None and int(size) > MAX_AUDIO_BYTES:
            raise RuntimeError("Cartesia response exceeds audio size limit")
        audio = response.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES or not audio.startswith(b"RIFF"):
        raise RuntimeError("Invalid or oversized Cartesia audio")
    return audio


class VoiceApp:
    def __init__(self, config: Config, *, engine=None, premium=cartesia_clive):
        self.config = config
        self.engine = engine if engine is not None else KokoroEngine(config.cpu_threads)
        self.premium = premium
        self.lock = threading.Lock()
        self.last_latency_ms = None
        self.requests = 0
        self.errors = 0

    def status(self) -> dict:
        return {
            "service": "jarvis-voice", "model": "hexgrad/Kokoro-82M",
            "loaded": bool(self.engine.ready),
            "voice": self.config.default_voice,
            "speed": self.config.default_speed,
            "premium_available": self.config.premium_enabled,
            "busy": self.lock.locked(),
            "rss_mb": rss_mb(),
            "max_rss_mb": self.config.max_rss_mb or None,
            "last_latency_ms": self.last_latency_ms,
            "requests": self.requests,
            "errors": self.errors,
        }

    def synthesize(self, data: object) -> tuple[bytes, str]:
        if not isinstance(data, dict) or set(data) - {"text", "voice", "speed", "provider"}:
            raise ValueError("unknown request fields")
        text = safe_text(data.get("text"))
        provider = data.get("provider", "kokoro")
        if provider not in ("kokoro", "clive"):
            raise ValueError("provider must be kokoro or clive")
        if provider == "clive" and not self.config.premium_enabled:
            raise PermissionError("Premium voice is not enabled")
        voice = data.get("voice", self.config.default_voice)
        if not isinstance(voice, str) or voice not in ALLOWED_VOICES:
            raise ValueError("Unrecognized voice")
        speed = valid_speed(data.get("speed"), self.config.default_speed)
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("voice service is busy")
        start = time.monotonic()
        try:
            current_rss = rss_mb()
            if (self.config.max_rss_mb and current_rss is not None
                    and current_rss >= self.config.max_rss_mb * 0.80):
                raise MemoryError("memory headroom below 20 percent")
            audio = (self.premium(text, speed, self.config.cartesia_key)
                     if provider == "clive" else self.engine.speak(text, voice, speed))
            if len(audio) > MAX_AUDIO_BYTES:
                raise RuntimeError("Audio exceeds response limit")
            self.requests += 1
            self.last_latency_ms = round((time.monotonic() - start) * 1000)
            return audio, provider
        except Exception:
            self.errors += 1
            raise
        finally:
            self.lock.release()


def make_handler(app: VoiceApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JarvisVoice/1.0"
        sys_version = ""

        def log_message(self, fmt, *args):
            # stdlib's default request log includes the raw URL (and any query).
            # Emit only an intentionally content-free request record.
            LOG.debug("voice_http handled request")

        def _send(self, code: int, content: bytes, mime="application/json", provider=""):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if provider:
                self.send_header("X-Jarvis-Voice-Provider", provider)
            self.end_headers()
            self.wfile.write(content)

        def _error(self, code: int, message: str):
            self._send(code, json.dumps({"error": message}).encode())

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            correct = "Bearer " + app.config.token
            return hmac.compare_digest(supplied.encode("utf-8"), correct.encode("utf-8"))

        def do_GET(self):
            if not self._authorized():
                return self._error(401, "unauthorized")
            if self.path != "/v1/status":
                return self._error(404, "not found")
            self._send(200, json.dumps(app.status()).encode())

        def do_POST(self):
            if not self._authorized():
                return self._error(401, "unauthorized")
            if self.path != "/v1/speak":
                return self._error(404, "not found")
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                return self._error(415, "application/json required")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                return self._error(400, "invalid request length")
            if not 1 <= length <= MAX_REQUEST_BYTES:
                return self._error(413, "request too large or missing length")
            try:
                body = json.loads(self.rfile.read(length))
                audio, provider = app.synthesize(body)
                self._send(200, audio, "audio/wav", provider)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                self._error(400, str(error))
            except PermissionError:
                self._error(403, "premium provider is disabled")
            except BlockingIOError:
                self._error(429, "voice worker busy; retry later")
            except MemoryError:
                self._error(503, "insufficient memory headroom")
            except Exception:
                LOG.exception("Voice synthesis failed; details omitted from user response")
                self._error(503, "voice temporarily unavailable")
    return Handler


def run() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    config = Config.from_env()
    app = VoiceApp(config)
    with ThreadingHTTPServer((config.host, config.port), make_handler(app)) as server:
        LOG.info("Jarvis voice service listening on %s:%s (private VLAN only)", config.host, config.port)
        server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    run()
