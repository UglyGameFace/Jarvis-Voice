#!/usr/bin/env bash
# One-time private GitHub repository bootstrap. Run from an extracted archive.
# Never accepts a token as a command argument and never force-pushes.
set -euo pipefail
repo='UglyGameFace/Jarvis-Voice'
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
for cmd in git gh python; do
  if ! command -v "$cmd" >/dev/null; then
    echo "Missing $cmd. In Termux: pkg install git gh python -y" >&2
    exit 1
  fi
done
python scripts/verify_repo.py
if ! gh auth status >/dev/null 2>&1; then
  echo 'GitHub login required. Follow the browser instructions and authenticate your own account.'
  gh auth login --web --git-protocol https
fi
user="$(gh api user --jq '.login')"
if [[ "$user" != 'UglyGameFace' ]]; then
  echo "Authenticated as $user, not UglyGameFace; refusing to create in another account." >&2
  exit 1
fi
if gh repo view "$repo" >/dev/null 2>&1; then
  echo "Repository $repo already exists. Refusing to overwrite it; use the GitHub connector for subsequent updates." >&2
  exit 1
fi
if [[ -e .git ]]; then
  echo 'Local folder already has Git metadata; refusing to change its history.' >&2
  exit 1
fi
git init -b main
git config user.name "$user"
userid="$(gh api user --jq '.id')"
git config user.email "${userid}+${user}@users.noreply.github.com"
git add --all
git commit -m 'Initial JARVIS Voice service with CI-gated Discloud deploy'
gh repo create "$repo" --private --source=. --remote=origin --push \
  --description 'Private self-hosted Kokoro TTS service for Jarvis, with optional Cartesia Clive'
printf '\nRepository created and source pushed: https://github.com/%s\n' "$repo"
echo 'Discloud voice app, GitHub Actions secrets and opt-in deploy variable still require account setup.'
