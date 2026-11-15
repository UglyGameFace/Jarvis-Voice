# JARVIS Voice release status (2026-11-15)

Objective: dedicated GitHub repository with CI-gated push-to-main Discloud deployment, Kokoro British male defaults, optional manually selected Clive.

Source: repository-ready ZIP for owner to initialize at `UglyGameFace/Jarvis-Voice`. GitHub connector can edit existing repositories but does not expose repository creation in this session. **No GitHub repo has been created, no changes pushed, and no app deployed yet.**

Code verified locally: CI package checks, Python unittest suite with simulated Kokoro and Cartesia, bytecode compile. No real Kokoro model or Discloud host tested.

Gate: GitHub Actions repository variable `JARVIS_VOICE_AUTO_DEPLOY=true` required for deploy; `DISCLOUD_TOKEN` and `DISCLOUD_VOICE_APP_ID` must reference a separate Discloud app, never `RivaL-Intelligence`. Deploy action pinned to official `discloud/deploy-action` v1 commit.

Discloud: private VLAN `jarvis-voice:8777`, tentative `RAM=2048`, separate from LFM3's configured 2450MB. Must measure platform plan capacity, package install (especially eSpeak fallback), actual CPU/RSS and production behavior before enabling deploy. No Jarvis website or authenticated proxy installed by this package.

Next: create a GitHub repository, import the ZIP contents, create the dedicated Discloud app through dashboard, configure secrets, measure headroom, then enable auto-deploy variable. Avoid also enabling Discloud's native GitHub auto-deploy: that would duplicate deploys with the Actions workflow.
