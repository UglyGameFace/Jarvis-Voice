# JARVIS Voice

Private, standalone Kokoro speech service with British voices. Its default is `bm_george` at speed `0.94`. Cartesia Clive is disabled unless explicitly enabled.

## GitHub -> Discloud

Only one GitHub Actions secret is required to bootstrap and deploy: `DISCLOUD_TOKEN`. On every push to `main`, the workflow must pass the Python tests and package checks before `scripts/deploy_discloud.py` runs.

The deployment script uses Discloud's authenticated API to find the one app named `Jarvis-Voice`, verifies that its main file is `server.py`, and updates that app. If no matching app exists, it creates a separate application from `discloud.config` (`TYPE=bot`, `VLAN=true`, `RAM=2048`). It refuses duplicate names or a conflicting app. It never targets `RivaL-Intelligence` or changes its configured 2450 MB. Insufficient Discloud account RAM may prevent the new app from being created.

**No `DISCLOUD_VOICE_APP_ID` secret or `JARVIS_VOICE_AUTO_DEPLOY` variable is needed now.** Do not enable Discloud's separate native GitHub auto-deploy alongside this workflow.

### Private voice authentication

The script derives a stable, separate 43-character voice credential from the Discloud API token using HMAC-SHA256. It is neither logged nor committed: the deployment sends it only in a temporary `.env` inside the private Discloud upload. If you prefer an independent credential, add the optional GitHub Actions secret `JARVIS_VOICE_TOKEN` (32-256 characters). Changing the account token also rotates the derived voice credential. The future Jarvis web backend must use the matching private voice credential, never expose it to browsers, and coordinate any rotation.

### Tests

```sh
python -m pip install 'numpy>=1.26,<3'
python -m compileall -q server.py scripts tests
python -m unittest discover -s tests -v
python scripts/verify_repo.py
```

## HTTP API

The private Discloud service binds `0.0.0.0:8777` on the VLAN and requires an `Authorization: Bearer <JARVIS_VOICE_TOKEN>` header for `GET /v1/status` and `POST /v1/speak`. Synthesis request example:

```json
{"text":"Good evening. JARVIS online.","voice":"bm_george","speed":0.94,"provider":"kokoro"}
```

Output is WAV. Four Kokoro British male options are available, and Cartesia requires an additional private API key and deliberate provider selection.

**Current limitations:** GitHub Actions has repeatedly failed before a runner starts, so no new remote tests or deployments are verified. This may require investigation of repository Actions permissions, runner provisioning, or billing. A successful upload in the future will still not prove actual Kokoro model inference, memory headroom, or Cloudflare-to-Discloud connectivity. Cloudflare cannot simply call a private VLAN hostname: Jarvis needs a separate secure backend bridge.

See `STATUS.md` for the current state.