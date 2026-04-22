# Project Context

## What this is
A Python webhook deployed on Google Cloud Functions that bridges Telegram and Asana. One bot handles all routing via a Google Sheet instead of separate deployments.

**Group chats:** @mention the bot (optionally with `/emergency`, `/hq`, or `/franchisees`) to create an Asana task from the message or replied-to message.

**Private DMs:** Forward one or more messages to build a draft, then finalize with a command + optional description. Direct text also creates a task immediately.

**Routing:** User→project mapping lives in a Google Sheet (`Users` tab). Section GIDs are in the `Config` tab. Pending draft messages are stored in the `Pending` tab.

## AI context files
- `.ai/conventions.md` — Python naming rules, code style, logging
- `.ai/constraints.md` — hard limits, deployment rules, secret handling
- `.ai/profile.md` — project owner background and collaboration style
- `.ai/workflow.md` — deploy cycle, Sheets setup, env vars reference

## Non-negotiable rules
- Never run `gcloud functions deploy`, `git push`, or any deploy command — user deploys manually
- Never hardcode secrets — all secrets come from GCF environment variables (`configs/env.yaml`)
- `configs/env.yaml` is gitignored and contains real credentials — never read or print its contents
- Allowed dependencies: `requests`, `gspread`, `google-auth` — nothing else without approval
- Never call `session_clear()` from the group chat handler — group tasks must not touch private DM sessions
- `build_task_content()` is the designated OpenAI hook point — all task name/notes formatting goes through it
