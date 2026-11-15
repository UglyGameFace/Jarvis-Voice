# JARVIS Voice engineering status | 2026-11-15

**Repository:** `UglyGameFace/Jarvis-Voice`, private, `main`. User created repository and reports adding the `DISCLOUD_TOKEN` GitHub Actions secret. Secret values cannot be read or verified by this GitHub connector.

**Implemented:** `scripts/deploy_discloud.py` now bootstraps or updates only the isolated `Jarvis-Voice` app using the Discloud API. The workflow tests first and then deploys on `main`. No `DISCLOUD_VOICE_APP_ID` or `JARVIS_VOICE_AUTO_DEPLOY` setting is required. Optional independent `JARVIS_VOICE_TOKEN`, otherwise stable domain-separated HMAC from Discloud token. The deployment ZIP contains only three runtime files and an ephemeral `.env`; premium Clive remains disabled.

**CI blocker:** Original workflow run `43760223218` and follow-up runs failed within seconds **before GitHub assigned a runner**; returned job steps are empty. Tests did not execute. The source-level test suite was locally validated in the original prepared package before the repository upload, but the new auto-provisioning code has not been remotely executed. Root cause of runner failure is not confirmed (inspect repo Actions settings, runner quota/billing).

**Production not verified:** Discloud app creation, token propagation, heavy dependencies, model weights, Kokoro speech quality, restart and memory behavior, and website integration are not yet evidenced. Discloud memory requested for a new isolated app is an unbenchmarked 2048 MB, in addition to the existing LFM3 service's 2450 MB. No LFM3 RAM or code was changed. If account quota is insufficient, bootstrap fails without touching other apps.

**Next action:** fix GitHub Actions runner execution on this private repository, then inspect its CI run and the Discloud `Jarvis-Voice` app. Do not claim live speech until audio and RAM are measured.