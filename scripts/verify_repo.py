"""Fail CI for accidental repo packaging mistakes, unsupported deployment layouts."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
config = dict(
    line.split("=", 1)
    for raw in (root / "discloud.config").read_text().splitlines()
    if (line := raw.strip()) and not line.startswith("#") and "=" in line
)
assert config["TYPE"] == "bot", "private VLAN service should not become public site"
assert config["MAIN"] == "server.py"
assert config["VLAN"] == "true"
assert config["HOSTNAME"] == "jarvis-voice"
assert int(config["RAM"]) >= 1024, "RAM must be explicitly sized, not the 100 MB default"

required = ["server.py", "requirements.txt", "discloud.config", ".gitignore", ".discloudignore", ".github/workflows/voice-ci-deploy.yml", "scripts/publish-from-termux.sh"]
for name in required:
    assert (root / name).is_file(), f"missing: {name}"
ignore = (root / ".gitignore").read_text().splitlines()
assert ".env" in ignore
assert ".env.example" not in ignore
assert not (root / ".env").exists(), "Never ship a real .env file"
assert not list(root.rglob("*.safetensors")), "Never commit model weights"
assert not list(root.rglob("*.gguf")), "Never commit model weights"
workflow = (root / ".github/workflows/voice-ci-deploy.yml").read_text()
for needle in ["needs: [tests]", "JARVIS_VOICE_AUTO_DEPLOY", "DISCLOUD_VOICE_APP_ID", "discloud/deploy-action@fae7024653d941a19daa2b6f56d2ae208e008c54", "branches: [main]"]:
    assert needle in workflow, f"missing safety gate: {needle}"
assert not re.search(r"^\s*env:\s*\$\{\{\s*secrets\.", workflow, re.M), "Avoid passing entire secrets bundle"
print("CI package and safety checks passed")
