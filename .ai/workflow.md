## Deploy Cycle
AI generates code → user reviews locally → user runs `./deploy.sh` or `./hq.deploy.sh` → user tests live via Telegram.

The deploy scripts: deploy the GCF, fetch the function URL, and register it as the Telegram webhook automatically.

## Two Bot Instances
Both instances run the same `main.py`. Config differences are in `configs/env.yaml` vs `configs/hq.env.yaml`:
- `TELEGRAM_TOKEN` — different bot token per instance
- `ASANA_PROJECT_ID` — different Asana project per instance
- `ASANA_TOKEN` — may be shared or separate
- `ALLOWED_USER_IDS` — allowlist for private chat access
- `DUE_DATE_DAYS` — optional, sets task due date N days from today

## Local Testing
Use `sample.json` as a payload fixture for manual curl tests against a locally-running function or the live GCF endpoint. Keep `sample.json` updated when adding new message types.

## Environment Setup
`preconfig.sh` sets the correct gcloud account (`vlad.kramarenko@idealsiding.com`) — run before any gcloud commands.

## Version Control
All changes must be atomic and git-friendly. No generated or compiled files committed.
