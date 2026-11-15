"""Safe, idempotent Discloud bootstrap from GitHub Actions (stdlib only)."""
from __future__ import annotations
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.request
import zipfile

API = "https://api.discloud.app/v2"
NAME = "Jarvis-Voice"
MAIN = "server.py"
ARTIFACTS = ("discloud.config", "server.py", "requirements.txt")


def private_token(account_token: str, override: str = "") -> str:
    if override:
        if not 32 <= len(override) <= 256:
            raise ValueError("JARVIS_VOICE_TOKEN must be 32..256 characters")
        return override
    if len(account_token) < 32:
        raise ValueError("DISCLOUD_TOKEN missing or too short")
    key = hmac.new(account_token.encode(), b"jarvis-voice-private-auth-v1",
                   hashlib.sha256).digest()
    return base64.urlsafe_b64encode(key).decode().rstrip("=")


def app_id_for(apps: list[dict]) -> str | None:
    if not isinstance(apps, list):
        raise ValueError("Invalid Discloud app list")
    matched = [app for app in apps if app.get("name") == NAME]
    if not matched:
        return None
    if len(matched) != 1 or matched[0].get("mainFile") != MAIN:
        raise ValueError("Ambiguous or non-Jarvis app; refusing to modify it")
    app_id = matched[0].get("id")
    if not isinstance(app_id, str) or not app_id or any(c in app_id for c in "/?#"):
        raise ValueError("Invalid Discloud app id")
    return app_id


def package(root: Path, voice_token: str) -> bytes:
    config = (root / "discloud.config").read_text(encoding="utf-8")
    for required in ("NAME=Jarvis-Voice\n", "MAIN=server.py\n",
                     "VLAN=true\n", "TYPE=bot\n"):
        if required not in config:
            raise ValueError("Discloud config no longer identifies the private voice app")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zipout:
        for name in ARTIFACTS:
            path = root / name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"Missing or symlinked deployment file: {name}")
            zipout.write(path, name)
        zipout.writestr(".env",
                        f"JARVIS_VOICE_TOKEN={voice_token}\n"
                        "JARVIS_CARTESIA_ENABLED=false\n"
                        "JARVIS_KOKORO_VOICE=bm_george\n"
                        "JARVIS_VOICE_SPEED=0.94\n"
                        "JARVIS_VOICE_CPU_THREADS=2\n")
    return out.getvalue()


def multipart(zipbytes: bytes) -> tuple[bytes, str]:
    boundary = "jarvis-voice-" + secrets.token_hex(16)
    body = (f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="jarvis-voice.zip"; filename="jarvis-voice.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n").encode()
    body += zipbytes + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def api(token: str, method: str, path: str, body: bytes | None = None,
        mime: str | None = None) -> dict:
    headers = {"api-token": token, "User-Agent": "Jarvis-Voice-GitHub/1"}
    if mime:
        headers["Content-Type"] = mime
    req = urllib.request.Request(API + path, data=body,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            value = json.loads(response.read(524288))
    except urllib.error.HTTPError as exc:
        try:
            error_body = json.loads(exc.read(4096))
            detail = error_body.get("message", "") if isinstance(error_body, dict) else ""
            if not isinstance(detail, str):
                detail = ""
            # Never echo either credential even if a remote error includes one.
            detail = detail.replace(token, "[REDACTED]")
            detail = detail.replace(private_token(token), "[REDACTED]")
            detail = "".join(c for c in detail if c.isprintable())[:220]
        except (ValueError, UnicodeDecodeError):
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Discloud HTTP {exc.code} on {method} {path}{suffix}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError("Cannot reach Discloud API") from exc
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise RuntimeError(f"Discloud rejected {method} {path}; inspect app quota/logs")
    return value


def deploy(root: Path, account_token: str, override: str = "") -> tuple[str, str]:
    private = private_token(account_token, override)
    contents = package(root, private)
    existing = app_id_for(api(account_token, "GET", "/app/all").get("apps"))
    body, mime = multipart(contents)
    if existing:
        api(account_token, "PUT", f"/app/{existing}/commit", body, mime)
        return existing, "updated"
    result = api(account_token, "POST", "/upload", body, mime)
    new = result.get("app") or {}
    if new.get("name") != NAME or new.get("mainFile") != MAIN:
        raise RuntimeError("Discloud returned an unexpected created app")
    app_id = new.get("id")
    if not isinstance(app_id, str) or not app_id:
        raise RuntimeError("Discloud did not return a valid voice app ID")
    return app_id, "created"


if __name__ == "__main__":
    account_token = os.environ.get("DISCLOUD_TOKEN", "")
    if not account_token:
        raise SystemExit("Missing GitHub Actions secret DISCLOUD_TOKEN")
    try:
        app_id, outcome = deploy(Path(__file__).resolve().parent.parent,
                                 account_token, os.environ.get("JARVIS_VOICE_TOKEN", ""))
    except (RuntimeError, ValueError) as exc:
        print(f"Deployment blocked: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Isolated Discloud app {app_id} {outcome}. "
          "Upload alone does not prove Kokoro audio works.")
