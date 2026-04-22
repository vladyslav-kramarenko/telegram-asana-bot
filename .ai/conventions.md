## Naming Philosophy
Names must be self-documenting — no comment needed to explain purpose.

**Functions** — use verb + noun:
- `create_asana_task` ✓ vs `create` ✗
- `attach_image_to_asana_task` ✓ vs `attach` ✗
- `send_telegram_confirmation` ✓ vs `notify` ✗

**Variables** — full words, no abbreviations except universally known ones (`url`, `id`, `gid`):
- `task_details` ✓ vs `td` ✗
- `photo_file_id` ✓ vs `fid` ✗
- `chat_type` ✓ vs `ct` ✗

**Booleans** — prefix with `is`, `has`, or `should`:
- `is_this_bot_mentioned`, `success`

## Code Style
- Single file (`main.py`) — keep it that way unless complexity genuinely requires splitting
- All config loaded from `os.environ.get()` at module level with clear names
- Return tuples `(status, data)` from `parse_message` — status is `"success"`, `"error"`, or `"ignore"`
- Never raise exceptions in handlers — catch and log, then return `"ok", 200`

## Logging
- Use `print()` for all logging (GCF routes stdout to Cloud Logging)
- Prefix log lines with emoji for quick log scanning: `✅` success, `❌` failure, `⚠️` warning, `📥` incoming, `📋` parsed
- Always log the raw incoming payload at DEBUG level: `print("📥 Raw payload:", json.dumps(data, indent=2))`
- Never log secret values (tokens, credentials)
