# Project Context

## What this is
A Python webhook deployed on Google Cloud Functions that bridges Telegram and Asana. When a user @mentions the bot in a Telegram group (or DMs it from an allowlisted account), it creates an Asana task with the message content and optionally attaches photos.

Two separate bot instances share one codebase (`main.py`), differentiated by config files:
- **Main bot** — `configs/env.yaml`, deployed via `deploy.sh` as `telegram_asana_webhook`
- **HQ bot** — `configs/hq.env.yaml`, deployed via `hq.deploy.sh` as `hq_telegram_asana_webhook`

## AI context files
- `.ai/conventions.md` — Python naming rules, code style, logging
- `.ai/constraints.md` — hard limits, deployment rules, secret handling
- `.ai/profile.md` — project owner background and collaboration style
- `.ai/workflow.md` — deploy and review cycle

## Non-negotiable rules
- Never run `gcloud functions deploy`, `git push`, or any deploy command — user deploys manually
- Never hardcode secrets — all secrets come from GCF environment variables (loaded from `configs/*.env.yaml`)
- `configs/*.env.yaml` files are gitignored and contain real credentials — never read or print their contents
- Do not add dependencies beyond `requests` unless the owner approves — the function runs in a minimal GCF environment
