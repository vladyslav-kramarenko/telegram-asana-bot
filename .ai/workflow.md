## Deploy Cycle
AI generates code → user reviews locally → user runs `./deploy.sh` → user tests live via Telegram.

The deploy script deploys the GCF, fetches the function URL, and registers it as the Telegram webhook automatically.

## Single Bot
One bot, one function (`telegram_asana_webhook`), one config file (`configs/env.yaml`).

## Env Vars (configs/env.yaml)
| Key | Required | Description |
|-----|----------|-------------|
| `TELEGRAM_TOKEN` | yes | Bot token from @BotFather |
| `ASANA_TOKEN` | yes | Asana Personal Access Token |
| `DEFAULT_ASANA_PROJECT_ID` | yes | Fallback project GID for users not in Sheets |
| `GOOGLE_SHEET_ID` | yes | Spreadsheet ID from the URL |
| `DUE_DATE_DAYS` | no | Set task due date N days from today |

Removed: `ASANA_PROJECT_ID`, `ALLOWED_USER_IDS` (both replaced by Sheets).

## Google Sheets Setup (one-time)
The GCF service account must have **Editor** access to the spreadsheet.
Grant it via: Share → paste the GCF service account email (visible in Cloud Console → IAM).

**Required tabs and headers:**

`Users`
```
user_id | display_name | asana_project_id
```

`Pending`
```
user_id | chat_id | content | photo_file_id | forwarded_from | timestamp
```

Users tab is cached in-memory for 5 minutes per GCF instance. Pending is always read live.

Section routing is handled by Asana automation rules (not by the bot). Commands prefix the task name: `/hq` → `HQ_`, `/emergency` → `EMERGENCY_`, `/franchisees` → `FRANCHISEES_`. Set up one rule per project: "if task name starts with X, move to section Y".

## Private DM Flow
1. User forwards messages → each stored in `Pending` tab, bot confirms count
2. User sends `/emergency`, `/hq`, or `/franchisees` (+ optional description) → task created from all pending + description, Pending rows cleared
3. User sends plain text (no forward) → immediate task, no session involved
4. `/cancel` → clears Pending for that user

## Commands (group and private)
- `/emergency` — creates task in Emergency section
- `/hq` — creates task in HQ section
- `/franchisees` — creates task in Franchisees section
- `/cancel` — (private only) discards current draft

## OpenAI Integration (future)
Replace the body of `build_task_content()` in `main.py`. No other changes needed.
Inputs: `pending_items`, `user_description`, `author_name`, `source` → outputs: `(task_name, notes)`.

## Version Control
All changes must be atomic and git-friendly. No generated or compiled files committed.
`preconfig.sh` sets the correct gcloud account — run before any gcloud commands.
