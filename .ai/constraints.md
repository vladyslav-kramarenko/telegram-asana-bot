## Runtime Limits
- GCF HTTP functions have a **60-second default timeout** — keep all API calls (Telegram, Asana, Sheets) fast; no retry loops
- Always return HTTP 200 to Telegram even on internal errors — Telegram retries on non-200, which causes duplicate tasks

## Secrets — NEVER do these
- Never hardcode tokens, project IDs, or user IDs in `main.py`
- All secrets live in `configs/env.yaml` — gitignored, never printed or logged
- `.env` is for local testing only; GCF reads from `--env-vars-file` at deploy time

## Deployment — NEVER do these
- Never suggest or run `gcloud functions deploy` — user deploys manually via `deploy.sh`
- Never suggest or run `git push` — user controls all version control operations
- AI role: generate code → user reviews locally → user runs deploy script → user tests live

## Bot Identity
- The bot fetches its own username via `getMe` and only responds to @mentions of itself (group chats)
- `BOT_USERNAME` is module-level cached for warm-start reuse — never remove this check
- Supporting multiple bots in the same group is a deliberate design constraint

## Session Safety
- `session_clear(user_id)` must NEVER be called from `handle_group_message()` — a user in a group may have an active private DM session that must not be destroyed by a group interaction
- Session is cleared only after confirmed Asana task creation success — on failure, the draft is preserved so the user can retry

## Data Safety
- If Asana task creation fails, always reply with an error to Telegram — never silently drop
- Image attachment failure is non-fatal — task is created without the image, no error surfaced to user
- Sheets read failure falls back to stale in-memory cache, then to DEFAULT_ASANA_PROJECT_ID, then rejects — never crashes the webhook

## Dependencies
Only `requests`, `gspread`, `google-auth` are allowed. Do not add packages without owner approval.
