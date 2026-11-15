"""Read-only Discloud RAM audit. Never changes allocations or restarts apps."""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request

API = "https://api.discloud.app/v2"
KNOWN = frozenset(("RivaL", "RivaL-Intelligence", "SniperPlug", "Dank Shield Helper",
                   "Watch Yo Mouf", "The Plug Minecraft", "Jarvis-Voice"))
RECEIPT = re.compile(r"\bmemory_receipt\s+([^\r\n]+)")
METRIC = re.compile(r"\b(current_mb|limit_mb|peak_mb|anon_mb|file_mb|oom_kills)=(\d+|None)\b")
USED = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(GiB|MiB|GB|MB|KB)\b")


def api_get(token, path):
    req = urllib.request.Request(API + path,
          headers={"api-token": token, "User-Agent": "Jarvis-RAM-audit/1"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            value = json.loads(resp.read(300_000))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Discloud read returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("Discloud read unavailable") from None
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise RuntimeError("Discloud read failed")
    return value


def usage_mb(value):
    if not isinstance(value, str):
        return None
    m = USED.search(value)
    if not m:
        return None
    scale = {"gib": 1024, "gb": 1000, "mib": 1.048576, "mb": 1, "kb": .001}
    return round(float(m[1]) * scale[m[2].lower()])


def latest_receipt(logs):
    if not isinstance(logs, str):
        return None
    matches = RECEIPT.findall(logs)
    if not matches:
        return None
    return {k: int(v) for k, v in METRIC.findall(matches[-1]) if v.isdecimal()}


def memory_receipt_summary(logs):
    """Count and max over available memory receipts, NOT an all-time peak."""
    if not isinstance(logs, str):
        return None
    samples=[]
    for row in RECEIPT.findall(logs):
        nums={k:int(v) for k,v in METRIC.findall(row) if v.isdecimal()}
        if "current_mb" in nums:
            samples.append(nums)
    if not samples:
        return None
    result={"observations":len(samples),
            "max_observed_current_mb":max(x["current_mb"] for x in samples)}
    peaks=[x["peak_mb"] for x in samples if "peak_mb" in x]
    if peaks:
        result["max_reported_peak_mb"]=max(peaks)
    ooms=[x["oom_kills"] for x in samples if "oom_kills" in x]
    if ooms:
        result["max_reported_oom_kills"]=max(ooms)
    return result


def summarize(user, apps, statuses, llm_receipt, llm_history=None):
    total, allocated = user.get("totalRamMb"), user.get("ramUsedMb")
    if type(total) is not int or type(allocated) is not int or not 0 <= allocated <= total:
        raise ValueError("Discloud account RAM unavailable")
    out = [f"Account: total={total} MB allocated={allocated} MB free={total-allocated} MB"]
    unknown_count, unknown_ram = 0, 0
    for app in sorted(apps, key=lambda v: str(v.get("name", ""))):
        name, ram = app.get("name"), app.get("ram")
        if type(ram) not in (int, float) or ram < 0:
            continue
        ram = round(ram)
        if name not in KNOWN:
            unknown_count += 1
            unknown_ram += ram
            continue
        status = statuses.get(name, {})
        used = usage_mb(status.get("memory"))
        cpu = status.get("cpu")
        cpu_match = re.search(r"(\d+(?:\.\d+)?)\s*%", cpu) if isinstance(cpu, str) else None
        cpu_text = cpu_match[1] + "%" if cpu_match else "?"
        out.append(f"App {name}: allocated={ram}MB online={bool(app.get('online'))} "
                   f"ramKilled={bool(app.get('ramKilled'))} instantaneous={used if used is not None else '?'}MB cpu={cpu_text}")
    out.append(f"Other apps (names hidden): count={unknown_count} allocated={unknown_ram}MB")
    if llm_receipt:
        out.append("LFM3 latest container memory receipt: " +
                   " ".join(f"{k}={llm_receipt[k]}" for k in
                            ("current_mb", "limit_mb", "peak_mb", "anon_mb", "file_mb", "oom_kills")
                            if k in llm_receipt))
    else:
        out.append("LFM3 peak memory receipt: not available in the retrieved log")
    if llm_history:
        out.append("LFM3 log-based memory history: " +
                   " ".join(f"{k}={v}" for k,v in llm_history.items()) +
                   " (only available log entries, not 14-day peak)")
    out.append("A single current usage reading is NOT enough to authorize memory reductions.")
    return out


def main():
    token = os.environ.get("DISCLOUD_TOKEN", "")
    if not token:
        raise SystemExit("Missing DISCLOUD_TOKEN secret")
    user = api_get(token, "/user").get("user")
    apps = api_get(token, "/app/all").get("apps")
    if not isinstance(user, dict) or not isinstance(apps, list):
        raise SystemExit("Incomplete RAM/account inventory")
    statuses, receipt, llm_history = {}, None, None
    for app in apps:
        name, app_id = app.get("name"), app.get("id")
        if (name not in KNOWN or not isinstance(app_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", app_id)):
            continue
        if app.get("online"):
            try:
                result = api_get(token, f"/app/{app_id}/status").get("apps")
                if isinstance(result, dict):
                    statuses[name] = result
            except RuntimeError:
                pass
        if name == "RivaL-Intelligence":
            try:
                result = api_get(token, f"/app/{app_id}/logs").get("apps")
                terminal = result.get("terminal") if isinstance(result, dict) else None
                if isinstance(terminal, dict):
                    receipt = latest_receipt(terminal.get("big"))
                    llm_history = memory_receipt_summary(terminal.get("big"))
            except RuntimeError:
                pass
    for line in summarize(user, apps, statuses, receipt, llm_history):
        print(line)


if __name__ == "__main__":
    main()
