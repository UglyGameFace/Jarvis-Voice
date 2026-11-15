# Jarvis Voice | self-hosted speech service

A standalone private CPU text-to-speech service for `jarvis.the420lobby.com`. Kokoro 82M provides British male speech by default (`bm_george`, 0.94 speed); Clive from Cartesia remains off unless explicitly enabled and selected. LFM3 generates the text, not audio. This service stays separate from `UglyGameFace/RivaL-Intelligence` and its source mirror.

## Repository and automatic deployment

This is a GitHub-repository-ready source tree. Create a **private** repository named `UglyGameFace/Jarvis-Voice` with default branch `main`, upload these files to its root (not inside a folder), and use the GitHub Actions workflow at `.github/workflows/voice-ci-deploy.yml`. The GitHub connector in the current ChatGPT session cannot create a new repository, so the archive does **not** represent a pushed repository or live deployment.

For the first provisioning of the *separate* `Jarvis-Voice` Discloud app, upload once from Discloud's Dashboard with this root `discloud.config`. The host must have sufficient free account allocation **in addition** to the existing LFM3 service. The 2048 MB configured limit is an unbenchmarked provisional size and can change after measurement. If the voice app is created under another app ID, configure the action's `DISCLOUD_VOICE_APP_ID` accordingly. Add `JARVIS_VOICE_TOKEN` (random 32+ characters) as a Discloud environment variable; don't store it in GitHub or the frontend. Start with `JARVIS_CARTESIA_ENABLED=false`.

Once its first synthesis and memory baseline are validated, in the new GitHub repository set:

- Actions secrets: `DISCLOUD_TOKEN` (Discloud account API token) and `DISCLOUD_VOICE_APP_ID` (voice app ID, **not** LFM3/RivaL's ID).
- Actions variable: `JARVIS_VOICE_AUTO_DEPLOY` = `true`.

After this, every push to `main` runs lightweight checks and, **only after they pass**, the official pinned Discloud deploy action uploads the runtime files to the specific voice app. Pull requests run tests only. Do **not** simultaneously enable Discloud's own GitHub auto-deploy, because this workflow already handles deployment and double redeploys would cause unnecessary downtime.

CI success proves only source tests. The Discloud deploy step confirms an upload, **not** a serving, warmed-up Kokoro model. Inspect the private status route and synthesize real audio after rollout. Model downloads, Python/Torch dependencies and CPU performance require platform verification. No model weights or secrets are tracked.

## Host requirements and caveats

- Python 3.11, Linux CPU, supported PyTorch wheels, outbound access to Kokoro model downloads, writable private model cache.
- `kokoro==0.9.4` and numerical dependencies from `requirements.txt`. British English's Misaki G2P may work without eSpeak, but unknown words can be skipped when `espeak-ng` is unavailable. Discloud's documented APT list does **not** explicitly include `espeak-ng`; verify it on the target host rather than assuming it can be installed via `APT`.
- Host service binds `0.0.0.0:8777` only within Discloud's private VLAN. Never expose port 8777 publicly or call it directly from the browser. An authenticated Jarvis backend route must proxy text to this service using a separate private token, rate limit users, and relay WAV responses.
- `RAM=2048` in `discloud.config` is **not** proof this is enough. Preserve the LFM3 app's existing configured `RAM=2450` unchanged. Benchmark idle RSS, synthesis peak RSS, CPU load, restart/OOM logs, p95 latency and capacity over at least 10 distinct phrases before enabling deployment automation.

## API

`GET /v1/status` with `Authorization: Bearer $JARVIS_VOICE_TOKEN` returns readiness and approximate RSS. Does not load weights.

`POST /v1/speak` with the same bearer header and JSON body:

```json
{"text":"Good evening. JARVIS online.","voice":"bm_george","speed":0.94,"provider":"kokoro"}
```

Returns `audio/wav`. Max 480 text characters, one concurrent inference, max 4MB audio. Requests may respond 429 when busy or 503 for memory pressure. Call it from a private backend over `http://jarvis-voice:8777` only, not from the phone browser.

For premium Clive, set `JARVIS_CARTESIA_ENABLED=true` and the private `CARTESIA_API_KEY` at the server, then explicitly request `provider=clive`. There is **no automatic paid fallback**.

## Manual development tests

```sh
python -m pip install 'numpy>=1.26,<3'
python -m compileall -q server.py tests
python -m unittest discover -s tests -v
python scripts/verify_repo.py
```

Testing the real model additionally requires `pip install -r requirements.txt` and host provisioning. The unit tests mock inference and do not assert live audio or deployment. See `.env.example` for private variables, `web/jarvis-voice-client.mjs` for the browser-side audio player to integrate **after** Jarvis has an authenticated server-side proxy, and `STATUS.md` for current evidence.

### Fastest Android/Termux first-time repository creation

After downloading and extracting the ZIP in Termux, install `pkg install git gh python unzip -y`, change into the extracted `jarvis-voice-repo-ready` folder and run `bash scripts/publish-from-termux.sh`. The script checks your current GitHub login, uses GitHub's own browser authorization if needed, creates a **private** `UglyGameFace/Jarvis-Voice` repository, and pushes the source to `main`. It refuses to overwrite an existing repository or switch accounts. It cannot run without the owner's GitHub login, and it does not create or authorize a Discloud app. The existing ChatGPT GitHub connector cannot perform initial repository creation itself.
