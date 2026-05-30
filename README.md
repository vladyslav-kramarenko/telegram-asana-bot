# Telegram to Asana Task Bot

A serverless webhook that bridges Telegram and Asana for Ideal Siding franchise operations. One Python codebase, multiple deployable bots — each differentiated entirely by environment variables.

## Bots

| Bot | Entry point | Users tab | Purpose |
|-----|-------------|-----------|---------|
| Main support | `telegram_asana_webhook` | `Users` | Franchise ops — routes tasks to per-user Asana projects |
| IT support | `it_support_webhook` | `IT_Users` | IT requests — routes to IT project sections by employee |

## Features

- **Group chats** — @mention the bot (optionally with a reply) to create an Asana task instantly
- **Private DMs** — simple flow: forward messages, bot bundles them into one task after 5 seconds; or `/task` for a manual draft session
- **Section routing** — each user has a designated `section_gid` in the sheet; tasks are placed directly into the correct section via API
- **Assignee** — each user row specifies who the Asana task is assigned to
- **Follower attribution** — the submitter's Asana GID is added as a follower so they receive notifications and appear on the task
- **AI task naming** — OpenAI generates the task title and description; plain-text fallback if unavailable
- **Image attachments** — photos are forwarded to Asana as attachments
- **Self-aware** — responds only to its own @mention; multiple bots can coexist in the same group

## Google Sheets setup

One spreadsheet, shared with the GCF service account (Editor access).

### `Users` tab — main bot
```
user_id | display_name | asana_project_id | section_gid | assignee | asana_user_gid
```

### `IT_Users` tab — IT support bot
```
user_id | display_name | asana_project_id | section_gid | assignee | asana_user_gid
```

| Column | Description |
|--------|-------------|
| `user_id` | Telegram user ID (find with `/myid`) |
| `display_name` | Human-readable name, used in task notes |
| `asana_project_id` | Asana project GID for this user's tasks |
| `section_gid` | Asana section GID tasks are placed in (blank = no section) |
| `assignee` | Email of the person responsible for the task in Asana |
| `asana_user_gid` | Asana user GID of the submitter, added as follower (blank = skip) |

### `Pending` tab — shared by all bots
```
user_id | chat_id | content | photo_file_id | forwarded_from | mode | timestamp
```
Stores in-progress DM drafts. Managed automatically.

## Deploying

```bash
./deploy.sh       # main bot
./it.deploy.sh    # IT support bot
```

First IT bot deploy: after the function URL is printed, paste it into `configs/env_it.yaml` as `GCF_URL`, then run `./it.deploy.sh` again so Cloud Tasks auto-finalize works.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | yes | Bot token from @BotFather |
| `ASANA_TOKEN` | yes | Asana Personal Access Token |
| `DEFAULT_ASANA_PROJECT_ID` | yes | Fallback project GID for users not in sheet |
| `GOOGLE_SHEET_ID` | yes | Spreadsheet ID from the URL |
| `CLOUD_TASKS_QUEUE` | yes | Full queue resource name for auto-finalize |
| `GCF_URL` | yes | This function's own URL (used by Cloud Tasks) |
| `OPENAI_API_KEY` | yes | OpenAI key for AI task generation |
| `USERS_TAB` | no | Sheet tab name for user lookup (default: `Users`) |
| `DUE_DATE_DAYS` | no | Set task due date N days from today |
| `OPENAI_MODEL` | no | OpenAI model (default: `gpt-4o-mini`) |

## Commands

| Command | Where | Action |
|---------|-------|--------|
| `/task` | Private | Start a multi-message draft session |
| `/done` | Private | Finalize draft and create Asana task |
| `/cancel` | Private | Discard current draft |
| `/myid` | Anywhere | Show your Telegram user ID |
| `/help` | Private | Show usage guide |
