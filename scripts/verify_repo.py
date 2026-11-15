"""Fail CI for unsafe JARVIS voice packaging and deployment boundaries."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = dict(
    line.split("=", 1)
    for raw in (root / "discloud.config").read_text().splitlines()
    if (line := raw.strip()) and not line.startswith("#") and "=" in line
)
assert config["NAME"] == "Jarvis-Voice"
assert config["TYPE"] == "bot"
assert config["MAIN"] == "server.py"
assert config["VLAN"] == "true"
assert config["HOSTNAME"] == "jarvis-voice"
assert int(config["RAM"]) >= 1024

for name in [
    "server.py", "requirements.txt", "discloud.config", ".gitignore",
    ".discloudignore", ".github/workflows/voice-ci-deploy.yml",
    "scripts/publish-from-termux.sh", "scripts/deploy_discloud.py",
    "tests/test_deploy_discloud.py",
]:
    assert (root / name).is_file(), f"Missing: {name}"
ignore = (root / ".gitignore").read_text().splitlines()
assert ".env" in ignore
assert ".env.example" not in ignore
assert not (root / ".env").exists(), "Never commit a real .env"
assert not list(root.rglob("*.safetensors"))
assert not list(root.rglob("*.gguf"))

workflow = (root / ".github/workflows/voice-ci-deploy.yml").read_text()
for needle in [
    "needs: [tests]", "branches: [main]", "secrets.DISCLOUD_TOKEN",
    "scripts/deploy_discloud.py", "github.event_name != 'pull_request'",
]:
    assert needle in workflow, f"Missing workflow safety boundary: {needle}"
assert "DISCLOUD_VOICE_APP_ID" not in workflow
assert "JARVIS_VOICE_AUTO_DEPLOY" not in workflow
assert "secrets.ENV" not in workflow
print("CI package and isolation checks passed")
