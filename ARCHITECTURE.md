# Architecture

## Overview

```
Telegram  ──►  GCF (main bot)     ──►  Asana (ops projects)
           ──►  GCF (IT bot)       ──►  Asana (IT project)
                      │
                      ▼
               Google Sheets
               (Users / IT_Users / Pending)
                      │
                      ▼
               Cloud Tasks
               (auto-finalize delay)
```

## Deployment model

One Python file (`main.py`), two independent GCF deployments. Each deployment is a fully isolated process with its own environment variables, in-memory cache, and Telegram token. There is no shared state between deployments at runtime.

| Deployment | Function name | Entry point | Config file |
|-----------|---------------|-------------|-------------|
| Main bot | `telegram_asana_webhook` | `telegram_asana_webhook` | `configs/env.yaml` |
| IT bot | `it_support_webhook` | `it_support_webhook` | `configs/env_it.yaml` |

The two entry points (`telegram_asana_webhook`, `it_support_webhook`) are thin aliases to `_handle_webhook`. All differentiation is driven by env vars:

- `TELEGRAM_TOKEN` — which Telegram bot responds
- `USERS_TAB` — which sheet tab provides user routing (`Users` vs `IT_Users`)
- `DEFAULT_ASANA_PROJECT_ID` — fallback project for unrecognized users

## Request flows

### Group chat
```
@mention  →  handle_group_message
          →  finalize_task
          →  asana_create_task        (project + assignee from sheet row)
          →  asana_add_to_section     (section_gid from sheet row, if set)
          →  asana_add_follower       (asana_user_gid from sheet row, if set)
          →  asana_attach_image       (if photo present)
          →  tg_send confirmation
```

### Private DM — simple flow (recommended)
```
forward/text  →  session_add (Pending tab, mode=auto)
              →  schedule_auto_finalize (Cloud Tasks, 5s delay)

[5 seconds later, Cloud Tasks POST]
              →  handle_auto_finalize
              →  session_clear
              →  finalize_task  (same path as group chat above)
```

### Private DM — draft flow
```
/task         →  session_add sentinel (mode=draft)
forward/text  →  session_add (mode=draft), each message
/done         →  session_get + finalize_task + session_clear
```

## Google Sheets

### Users / IT_Users tabs (same schema)
```
user_id | display_name | asana_project_id | section_gid | assignee | asana_user_gid
```
Cached in-memory per GCF instance for 5 minutes (`CACHE_TTL`). On cache miss, retried up to 3 times with exponential backoff. Stale cache is preserved on failure.

### Pending tab (shared)
```
user_id | chat_id | content | photo_file_id | forwarded_from | mode | timestamp
```
Written on every forwarded message or text in auto/draft mode. Cleared after successful task creation. `mode` is either `auto` (simple flow) or `draft` (manual session).

> **Known limitation:** The Pending tab is shared across both bot deployments. If the same Telegram user interacts with both bots simultaneously, their pending items could be mixed. In practice this is not an issue since the two bots serve different use cases.

## Asana task creation sequence

1. `asana_create_task` — creates the task in the project, sets assignee and due date
2. `asana_add_to_section` — moves task to the correct section (skipped if `section_gid` blank)
3. `asana_add_follower` — adds submitter as follower (skipped if `asana_user_gid` blank)
4. `asana_attach_image` — uploads photo attachment (non-fatal on failure)

Section assignment uses `POST /sections/{section_gid}/addTask` (direct API call), replacing the previous approach of name-prefix automation rules in Asana.

## Task content generation (`build_task_content`)

Single designated hook point for AI generation. Tries OpenAI first; falls back to plain-text assembly on any failure. Contract is stable: inputs `(pending_items, user_description, author_name, source)` → outputs `(task_name, notes)`. Replace the function body to swap the AI provider.

## In-memory globals (warm-start safe)

| Variable | Purpose |
|----------|---------|
| `BOT_USERNAME` | Cached bot @username from `getMe`, used for @mention detection |
| `_spreadsheet` | gspread spreadsheet client |
| `_tasks_client` | Cloud Tasks client |
| `_users_cache` | Cached rows from the active users tab |
| `_users_cache_ts` | Timestamp of last cache refresh |
| `_rate_limit` | Per-user request timestamps for rate limiting unauthorized users |

Each GCF deployment maintains its own copy of these globals. They are populated on first warm request and reused across subsequent requests on the same instance.

## Session safety rules

- `session_clear()` is never called from `handle_group_message` — a user may have an active private DM draft that must not be destroyed by a group interaction
- In `handle_auto_finalize`, `session_clear()` is called **before** `finalize_task` to prevent duplicate task creation if Cloud Tasks fires twice

## Cloud Tasks auto-finalize

Used to bundle multiple quickly-forwarded messages into one task without requiring the user to send a command. Each forwarded message schedules a new Cloud Tasks job (5s delay). The first job to fire clears the session; subsequent jobs find an empty session and exit. The `GCF_URL` env var must point to the function's own URL — each deployment needs its own value.
