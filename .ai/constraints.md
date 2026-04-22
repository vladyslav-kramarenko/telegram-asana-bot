## Runtime Limits
- GCF HTTP functions have a **60-second default timeout** — keep all API calls (Telegram, Asana) fast; no retry loops
- Always return HTTP 200 to Telegram even on internal errors — Telegram retries on non-200, causing duplicate tasks

## Secrets — NEVER do these
- Never hardcode tokens, project IDs, or user IDs in `main.py`
- All secrets live in `configs/env.yaml` and `configs/hq.env.yaml` — gitignored, never printed or logged
- `.env` is for local testing only; GCF reads from `--env-vars-file` at deploy time

## Deployment — NEVER do these
- Never suggest or run `gcloud functions deploy` — user deploys manually via `deploy.sh` or `hq.deploy.sh`
- Never suggest or run `git push` — user controls all version control operations
- AI role: generate code → user reviews locally → user runs deploy script → user tests live

## Bot Identity
- The bot is self-aware: it fetches its own username via `getMe` and only responds to @mentions of itself
- This supports multiple bots in the same Telegram group — never remove the self-awareness check
- `BOT_USERNAME` is module-level cached; the GCF instance may be warm-started across requests

## Data Safety
- If Asana task creation fails, always reply with an error to Telegram — never silently drop the request
- Image attachment failure is non-fatal — task is created without the image, no error is surfaced to the user
