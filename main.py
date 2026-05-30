import os
import json
import time
import datetime
import traceback
import requests
import gspread
from openai import OpenAI
from google.auth import default as google_auth_default
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

# ── CONFIG ────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN           = os.environ.get("TELEGRAM_TOKEN")
ASANA_TOKEN              = os.environ.get("ASANA_TOKEN")
DEFAULT_ASANA_PROJECT_ID = os.environ.get("DEFAULT_ASANA_PROJECT_ID")
GOOGLE_SHEET_ID          = os.environ.get("GOOGLE_SHEET_ID")
DUE_DATE_DAYS_STR        = os.environ.get("DUE_DATE_DAYS")
CLOUD_TASKS_QUEUE        = os.environ.get("CLOUD_TASKS_QUEUE")  # projects/PROJECT/locations/REGION/queues/QUEUE
GCF_URL                  = os.environ.get("GCF_URL")            # this function's own URL
OPENAI_API_KEY           = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL             = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
USERS_TAB                = os.environ.get("USERS_TAB", "Users")  # sheet tab for user routing
CLOUD_TASKS_SECRET       = os.environ.get("CLOUD_TASKS_SECRET", "")
WEBHOOK_SECRET           = os.environ.get("WEBHOOK_SECRET", "")

CACHE_TTL           = 300   # seconds
RATE_LIMIT_UNAUTH   = 5     # requests/min for unknown users
RATE_LIMIT_AUTH     = 20    # requests/min for authorized users
RATE_LIMIT_WINDOW   = 60    # seconds
PENDING_MAX_AGE     = 300   # seconds before a pending row is considered stale (5 min)

# ── IN-MEMORY CACHE (warm-start safe) ────────────────────────────────────────

BOT_USERNAME     = None
_spreadsheet     = None
_tasks_client    = None
_users_cache     = None
_users_cache_ts  = 0.0
_rate_limit      = {}     # user_id → [timestamp, ...]

# ── OPENAI CLIENT ─────────────────────────────────────────────────────────────

_openai_client = None

def _get_openai_client():
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client

# ── GOOGLE SHEETS CLIENT ──────────────────────────────────────────────────────

def _get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        creds, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        _spreadsheet = gspread.authorize(creds).open_by_key(GOOGLE_SHEET_ID)
    return _spreadsheet

# ── SHEETS DATA ACCESSORS ─────────────────────────────────────────────────────

def _refresh_users():
    global _users_cache, _users_cache_ts
    for attempt in range(3):
        try:
            _users_cache    = _get_spreadsheet().worksheet(USERS_TAB).get_all_records()
            _users_cache_ts = time.time()
            return
        except Exception as e:
            print(f"⚠️ {USERS_TAB} sheet error (attempt {attempt + 1}): {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s
    # all retries failed — keep existing cache if any

def get_all_users():
    if _users_cache is None or time.time() - _users_cache_ts > CACHE_TTL:
        _refresh_users()
    return _users_cache or []

def lookup_user(user_id):
    for row in get_all_users():
        if str(row.get("user_id")) == str(user_id):
            return row
    return None

def is_rate_limited(user_id, limit=RATE_LIMIT_UNAUTH):
    now  = time.time()
    hits = [t for t in _rate_limit.get(user_id, []) if now - t < RATE_LIMIT_WINDOW]
    hits.append(now)
    _rate_limit[user_id] = hits
    return len(hits) > limit

def is_authorized_private(user_id):
    """Private chat requires the user to exist in the users tab."""
    return lookup_user(user_id) is not None


# ── SESSION — Pending tab ─────────────────────────────────────────────────────

def session_add(user_id, chat_id, content, photo_file_id="", forwarded_from="", is_user_text=False, mode="auto"):
    try:
        _get_spreadsheet().worksheet("Pending").append_row([
            str(user_id), str(chat_id),
            content or "",
            photo_file_id or "",
            "__text__" if is_user_text else (forwarded_from or ""),
            mode,
            datetime.datetime.utcnow().isoformat(),
        ])
        return True
    except Exception as e:
        print(f"❌ session_add failed: {e}")
        return False

def _row_ts(row):
    try:
        return datetime.datetime.fromisoformat(row.get("timestamp", "")).timestamp()
    except Exception:
        return 0.0

def session_get(user_id):
    try:
        cutoff = time.time() - PENDING_MAX_AGE
        rows   = _get_spreadsheet().worksheet("Pending").get_all_records()
        return [
            r for r in rows
            if str(r.get("user_id")) == str(user_id) and _row_ts(r) >= cutoff
        ]
    except Exception as e:
        print(f"⚠️ session_get failed: {e}")
        return []

def cleanup_stale_pending():
    try:
        sheet  = _get_spreadsheet().worksheet("Pending")
        rows   = sheet.get_all_records()
        cutoff = time.time() - PENDING_MAX_AGE
        to_del = [i + 2 for i, r in enumerate(rows) if _row_ts(r) < cutoff]
        if not to_del:
            return
        for row_num in reversed(to_del):
            sheet.delete_rows(row_num)
        print(f"🧹 Removed {len(to_del)} stale Pending rows")
    except Exception as e:
        print(f"⚠️ cleanup_stale_pending failed: {e}")

def session_clear(user_id):
    try:
        sheet   = _get_spreadsheet().worksheet("Pending")
        rows    = sheet.get_all_records()
        to_del  = [i + 2 for i, r in enumerate(rows) if str(r.get("user_id")) == str(user_id)]
        for row_num in reversed(to_del):
            sheet.delete_rows(row_num)
    except Exception as e:
        print(f"❌ session_clear failed: {e}")

def is_in_draft_session(user_id):
    """True if the user explicitly started a /task draft (has mode=draft rows)."""
    return any(str(r.get("mode", "")) == "draft" for r in session_get(user_id))

# ── CLOUD TASKS — auto-finalize for simple flow ───────────────────────────────

def _get_tasks_client():
    global _tasks_client
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
    return _tasks_client

def schedule_auto_finalize(user_id, chat_id, delay_seconds=5):
    if not CLOUD_TASKS_QUEUE or not GCF_URL:
        print("⚠️ CLOUD_TASKS_QUEUE or GCF_URL not set — auto-finalize disabled")
        return
    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delay_seconds))
    window    = int(time.time() // 5)  # 5-second window — deduplicates batch forwards
    task_name = f"{CLOUD_TASKS_QUEUE}/tasks/finalize-{user_id}-{window}"
    task = tasks_v2.Task(
        name=task_name,
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=GCF_URL,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"_auto_finalize": {"user_id": user_id, "chat_id": chat_id, "secret": CLOUD_TASKS_SECRET}}).encode(),
        ),
        schedule_time=ts,
    )
    try:
        _get_tasks_client().create_task(parent=CLOUD_TASKS_QUEUE, task=task)
        print(f"✅ Auto-finalize scheduled for user {user_id} in {delay_seconds}s")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e) or "409" in str(e):
            print(f"ℹ️ Auto-finalize already queued for user {user_id}")
        else:
            print(f"❌ schedule_auto_finalize failed: {e}")

def handle_auto_finalize(user_id, chat_id):
    cleanup_stale_pending()
    pending = session_get(user_id)
    if not pending:
        print(f"⚠️ Auto-finalize for {user_id}: nothing pending (already handled)")
        return
    row         = lookup_user(user_id)
    author_name = str(row.get("display_name", "Unknown")) if row else "Unknown"
    session_clear(user_id)
    finalize_task(user_id, chat_id, None, pending, "", author_name, "Private Chat",
                  clear_session_after=False)

# ── TASK CONTENT BUILDER ── OpenAI swap point ─────────────────────────────────

def build_task_content(pending_items, user_description, author_name, source):
    """
    Returns (task_name, notes) from forwarded messages + optional user description.

    OpenAI hook: replace the body of this function to change generation.
    Contract is stable — inputs and outputs are unchanged by that swap.
      pending_items:    list of dicts with keys: content, forwarded_from, photo_file_id
      user_description: str | None — the user's own typed note
      author_name:      str
      source:           str — group title or "Private Chat"
    Returns: (task_name: str, notes: str)
    """
    text_items    = [i for i in pending_items if i.get("forwarded_from") == "__text__"]
    forward_items = [i for i in pending_items if i.get("forwarded_from") != "__text__"]

    if not user_description and text_items:
        user_description = " ".join(i.get("content", "") for i in text_items).strip()

    raw_parts = []
    for item in forward_items:
        origin  = item.get("forwarded_from", "")
        content = (item.get("content") or "").strip()
        if content:
            raw_parts.append(f"[Forwarded from {origin}]\n{content}" if origin else content)
    if user_description:
        raw_parts.append(f"[Note from {author_name}]\n{user_description}")
    raw_block = "\n\n---\n\n".join(raw_parts) if raw_parts else "[Forwarded media]"

    # ── OpenAI generation ─────────────────────────────────────────────────────
    try:
        ai_lines = []
        for item in forward_items:
            origin  = item.get("forwarded_from", "Unknown")
            content = (item.get("content") or "").strip()
            if content:
                ai_lines.append(f"[Forwarded from {origin}]\n{content}")
        if user_description:
            ai_lines.append(f"[Note from {author_name}]\n{user_description}")
        ai_input = "\n\n---\n\n".join(ai_lines) if ai_lines else raw_block

        system_prompt = (
            "You are an operations assistant for Ideal Siding, a franchise business. "
            "You receive messages forwarded from Telegram support chats and notes from franchise coordinators. "
            "Your job is to generate a clear, concise task for the operations team.\n\n"
            "Respond with valid JSON only in this exact shape:\n"
            '{"title": "...", "description": "..."}\n\n'
            "Rules:\n"
            "- title: one sentence, max 80 chars, action-oriented\n"
            "- description: 2-4 sentences summarising the situation, who reported it, and what action is needed\n"
            "- Preserve names of people and locations from the messages\n"
            "- Do not add information that is not in the messages"
        )

        client = _get_openai_client()
        if not client:
            raise ValueError("OPENAI_API_KEY not set")
        resp     = client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": ai_input},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        parsed   = json.loads(resp.choices[0].message.content)
        ai_title = (parsed.get("title") or "").strip()[:80]
        ai_desc  = (parsed.get("description") or "").strip()

        if ai_title:
            notes  = f"{ai_desc}\n\n--- Original Messages ---\n\n{raw_block}"
            notes += f"\n\nFrom: {author_name} | Source: {source}"
            return ai_title, notes

    except Exception as e:
        print(f"⚠️ OpenAI build_task_content failed: {e} — falling back to plain text")

    # ── Plain-text fallback ──────────────────────────────────────────────────
    note_sections = []
    if user_description:
        note_sections.append(f"Note: {user_description}")
    note_sections.append(f"Content:\n{raw_block}")
    note_sections.append(f"From: {author_name} | Source: {source}")

    if user_description:
        base_name = user_description[:80]
    elif raw_parts:
        base_name = raw_parts[0].split("\n")[-1][:80]
    else:
        base_name = f"Task from {author_name} in {source}"

    return base_name, "\n\n".join(note_sections)

# ── ASANA API ─────────────────────────────────────────────────────────────────

def asana_create_task(task_name, notes, project_id, assignee=None):
    if not ASANA_TOKEN or not project_id:
        print("❌ Missing ASANA_TOKEN or project_id.")
        return False, "Missing Asana config."

    payload = {
        "data": {
            "name":     task_name,
            "notes":    notes,
            "projects": [project_id],
        }
    }

    if assignee:
        payload["data"]["assignee"] = assignee

    if DUE_DATE_DAYS_STR and DUE_DATE_DAYS_STR.isdigit():
        due = datetime.date.today() + datetime.timedelta(days=int(DUE_DATE_DAYS_STR))
        payload["data"]["due_on"] = due.isoformat()

    try:
        r = requests.post(
            "https://app.asana.com/api/1.0/tasks",
            headers={"Authorization": f"Bearer {ASANA_TOKEN}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        print(f"✅ Asana task created: {r.json()['data'].get('gid')}")
        return True, r.json()
    except requests.exceptions.RequestException as e:
        detail = e.response.text if e.response is not None else str(e)
        print(f"❌ asana_create_task failed: {detail}")
        return False, detail

def asana_add_to_section(task_gid, section_gid):
    try:
        r = requests.post(
            f"https://app.asana.com/api/1.0/sections/{section_gid}/addTask",
            headers={"Authorization": f"Bearer {ASANA_TOKEN}", "Content-Type": "application/json"},
            json={"data": {"task": task_gid}},
        )
        r.raise_for_status()
        print(f"✅ Task {task_gid} added to section {section_gid}")
    except Exception as e:
        print(f"❌ asana_add_to_section failed: {e}")

def asana_add_follower(task_gid, asana_user_gid):
    try:
        r = requests.post(
            f"https://app.asana.com/api/1.0/tasks/{task_gid}/addFollowers",
            headers={"Authorization": f"Bearer {ASANA_TOKEN}", "Content-Type": "application/json"},
            json={"data": {"followers": [asana_user_gid]}},
        )
        r.raise_for_status()
        print(f"✅ Follower {asana_user_gid} added to task {task_gid}")
    except Exception as e:
        print(f"❌ asana_add_follower failed: {e}")

def asana_attach_image(task_gid, file_id):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        file_name = file_path.split("/")[-1]
        ext       = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
        ctype     = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(
            ext, "application/octet-stream"
        )
        with requests.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}", stream=True
        ) as img:
            img.raise_for_status()
            upload = requests.post(
                f"https://app.asana.com/api/1.0/tasks/{task_gid}/attachments",
                headers={"Authorization": f"Bearer {ASANA_TOKEN}"},
                files={"file": (file_name, img.raw, ctype)},
            )
            upload.raise_for_status()
        print(f"✅ Image attached to task {task_gid}")
        return True
    except Exception as e:
        print(f"❌ asana_attach_image failed: {e}")
        return False

# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────

def get_bot_username():
    global BOT_USERNAME
    if BOT_USERNAME is None:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe")
            r.raise_for_status()
            BOT_USERNAME = r.json()["result"]["username"]
            print(f"✅ Bot: @{BOT_USERNAME}")
        except Exception as e:
            print(f"🔥 getMe failed: {e}")
            BOT_USERNAME = ""
    return BOT_USERNAME

def tg_send(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload
        )
    except Exception as e:
        print(f"⚠️ tg_send failed: {e}")

# ── COMMAND & TEXT EXTRACTION ─────────────────────────────────────────────────

def _get_command(text, entity):
    return text[entity["offset"]: entity["offset"] + entity["length"]].split("@")[0].lower()

def has_command(text, entities, cmd):
    return any(
        _get_command(text, e) == cmd
        for e in (entities or []) if e.get("type") == "bot_command"
    )

def strip_entity_tokens(text, entities, types_to_strip):
    """Remove entity tokens by type from text (processes in reverse to preserve offsets)."""
    result = text
    for e in sorted((entities or []), key=lambda x: x["offset"], reverse=True):
        if e.get("type") in types_to_strip:
            s, end = e["offset"], e["offset"] + e["length"]
            result  = result[:s] + result[end:]
    return result.strip()

# ── TASK FINALIZATION ─────────────────────────────────────────────────────────

def finalize_task(user_id, chat_id, msg_id, pending_items, user_description,
                  author_name, source, clear_session_after=False):
    row        = lookup_user(user_id)
    project_id = str(row.get("asana_project_id") or "").strip() if row else ""
    project_id = project_id or DEFAULT_ASANA_PROJECT_ID
    if not project_id:
        tg_send(chat_id, "⚠️ No Asana project configured for you. Contact your admin.", reply_to=msg_id)
        return

    assignee       = str(row.get("assignee") or "").strip() or None if row else None
    section_gid    = str(row.get("section_gid") or "").strip() or None if row else None
    asana_user_gid = str(row.get("asana_user_gid") or "").strip() or None if row else None

    task_name, notes = build_task_content(pending_items, user_description, author_name, source)
    success, result  = asana_create_task(task_name, notes, project_id, assignee)

    if not success:
        tg_send(chat_id, "⚠️ Could not create Asana task. Check logs.", reply_to=msg_id)
        return

    if clear_session_after:
        session_clear(user_id)

    task_gid = result.get("data", {}).get("gid")
    if task_gid:
        if section_gid:
            asana_add_to_section(task_gid, section_gid)
        if asana_user_gid:
            asana_add_follower(task_gid, asana_user_gid)
        for item in pending_items:
            if item.get("photo_file_id"):
                asana_attach_image(task_gid, item["photo_file_id"])

    task_url = result.get("data", {}).get("permalink_url", "")
    reply    = "✅ Task created!"
    if task_url:
        reply += f"\n[View in Asana]({task_url})"
    tg_send(chat_id, reply, reply_to=msg_id)

# ── GROUP CHAT HANDLER ────────────────────────────────────────────────────────

def handle_group_message(message):
    bot_username = get_bot_username()
    text         = message.get("text", "")
    entities     = message.get("entities", [])
    chat_info    = message.get("chat", {})
    author_info  = message.get("from", {})

    is_mentioned = any(
        text[e["offset"]: e["offset"] + e["length"]] == f"@{bot_username}"
        for e in entities if e.get("type") == "mention"
    )
    if not is_mentioned:
        return

    chat_id = chat_info.get("id")
    msg_id  = message.get("message_id")
    source  = chat_info.get("title", "Group")
    user_id = author_info.get("id")

    if is_rate_limited(user_id, RATE_LIMIT_AUTH):
        print(f"🚫 Rate-limited user {user_id} in group")
        return

    description = strip_entity_tokens(text, entities, {"mention", "bot_command"})

    if "reply_to_message" in message:
        original      = message["reply_to_message"]
        author_name   = original.get("from", {}).get("first_name", "Unknown")
        original_text = original.get("text") or original.get("caption")
        photo_id      = original["photo"][-1]["file_id"] if "photo" in original else None
        if not original_text:
            original_text = "[Image]" if photo_id else "[Media]"
        content = (
            f"Comment: {description}\n---\nOriginal: {original_text}"
            if description else original_text
        )
    else:
        author_name = author_info.get("first_name", "Unknown")
        photo_id    = message["photo"][-1]["file_id"] if "photo" in message else None
        content     = description or ("[Image]" if photo_id else "")
        if not content:
            tg_send(chat_id, "⚠️ Please add text or reply to a message.", reply_to=msg_id)
            return

    pending_items = [{"content": content, "photo_file_id": photo_id or "", "forwarded_from": ""}]
    finalize_task(user_id, chat_id, msg_id, pending_items, "", author_name, source,
                  clear_session_after=False)

# ── PRIVATE CHAT HANDLER ──────────────────────────────────────────────────────

def handle_private_message(message):
    author_info = message.get("from", {})
    user_id     = author_info.get("id")
    chat_id     = message.get("chat", {}).get("id")
    msg_id      = message.get("message_id")
    author_name = author_info.get("first_name", "Unknown")

    text     = message.get("text") or message.get("caption") or ""
    entities = message.get("entities") or message.get("caption_entities") or []

    # /myid works for everyone — no auth or rate-limit required
    if has_command(text, entities, "/myid"):
        tg_send(chat_id, f"Your Telegram ID: `{user_id}`", reply_to=msg_id)
        return

    if not is_authorized_private(user_id):
        if is_rate_limited(user_id, RATE_LIMIT_UNAUTH):
            print(f"🚫 Rate-limited unauthorized user {user_id}")
        return

    if is_rate_limited(user_id, RATE_LIMIT_AUTH):
        print(f"🚫 Rate-limited authorized user {user_id}")
        return

    photo_id = message["photo"][-1]["file_id"] if "photo" in message else None
    is_fwd   = "forward_origin" in message or "forward_date" in message

    if has_command(text, entities, "/cancel"):
        session_clear(user_id)
        tg_send(chat_id, "🗑️ Draft cleared.", reply_to=msg_id)
        return

    if has_command(text, entities, "/help"):
        tg_send(chat_id, (
            f"*@{get_bot_username()}*\n\n"
            "*Simple flow (recommended)*\n"
            "Forward messages here — everything within 5 seconds is bundled into one Asana task.\n"
            "Add a note alongside forwards for extra context.\n\n"
            "*Draft flow (for multiple rounds of forwarding)*\n"
            "`/task` — start a draft session\n"
            "Forward messages and add notes, then:\n"
            "`/done` — create task\n"
            "`/cancel` — discard draft\n\n"
            "*Group chats*\n"
            f"Mention `@{get_bot_username()}` in a message or reply to create a task instantly.\n\n"
            "`/myid` — show your Telegram ID\n"
            "`/help` — show this message"
        ), reply_to=msg_id)
        return

    in_session = is_in_draft_session(user_id)

    # /task — enter multi-message draft mode
    if has_command(text, entities, "/task"):
        if in_session:
            tg_send(chat_id, "⚠️ You already have a draft. /cancel it first or finalize with /done.", reply_to=msg_id)
        else:
            session_add(user_id, chat_id, "", is_user_text=True, mode="draft")
            tg_send(
                chat_id,
                "📋 *Draft started.* Forward messages and add text, then:\n"
                "`/done` — create task\n"
                "`/cancel` — discard",
                reply_to=msg_id,
            )
        return

    # /done — finalize
    if has_command(text, entities, "/done"):
        description = strip_entity_tokens(text, entities, {"bot_command"})
        pending     = session_get(user_id)
        if not pending and not description:
            tg_send(chat_id, "⚠️ Nothing to create a task from.", reply_to=msg_id)
            return
        if not pending:
            pending = [{"content": description, "photo_file_id": photo_id or "", "forwarded_from": ""}]
            description = ""
        finalize_task(user_id, chat_id, msg_id, pending, description, author_name,
                      "Private Chat", clear_session_after=True)
        return

    # Ignore unrecognized commands — don't treat them as text
    if any(e.get("type") == "bot_command" for e in entities):
        return

    # Extract forwarded_from name
    forwarded_from = ""
    if is_fwd:
        origin = message.get("forward_origin", {})
        ftype  = origin.get("type", "")
        if ftype == "user":
            forwarded_from = origin.get("sender_user", {}).get("first_name", "")
        elif ftype == "channel":
            forwarded_from = origin.get("chat", {}).get("title", "")
        elif ftype == "hidden_user":
            forwarded_from = origin.get("sender_user_name", "Hidden")

    if is_fwd or photo_id:
        content = text or ("[Image]" if photo_id else "[Forwarded media]")
        if in_session:
            session_add(user_id, chat_id, content, photo_id, forwarded_from, mode="draft")
            count = len(session_get(user_id))
            tg_send(
                chat_id,
                f"📎 *{count} message{'s' if count > 1 else ''} in draft.*\n"
                "`/done` · `/cancel`",
                reply_to=msg_id,
            )
        else:
            session_add(user_id, chat_id, content, photo_id, forwarded_from, mode="auto")
            schedule_auto_finalize(user_id, chat_id)

    elif text:
        if in_session:
            session_add(user_id, chat_id, text, is_user_text=True, mode="draft")
            count = len(session_get(user_id))
            tg_send(
                chat_id,
                f"📎 *{count} message{'s' if count > 1 else ''} in draft.*\n"
                "`/done` · `/cancel`",
                reply_to=msg_id,
            )
        else:
            session_add(user_id, chat_id, text, is_user_text=True, mode="auto")
            schedule_auto_finalize(user_id, chat_id)

# ── WEBHOOK ENTRY POINTS ──────────────────────────────────────────────────────

def _handle_webhook(request):
    if not TELEGRAM_TOKEN:
        print("FATAL: TELEGRAM_TOKEN not set.")
        return "Configuration error", 500

    get_bot_username()

    try:
        data = request.get_json()
        if not data:
            return "Bad Request", 400

        # Cloud Tasks auto-finalize callback — handled before webhook secret check
        # because Cloud Tasks does not send X-Telegram-Bot-Api-Secret-Token
        if "_auto_finalize" in data:
            if not request.headers.get("X-CloudTasks-QueueName"):
                print("⚠️ _auto_finalize without Cloud Tasks header — ignored")
                return "ok", 200
            info = data["_auto_finalize"]
            if CLOUD_TASKS_SECRET and info.get("secret") != CLOUD_TASKS_SECRET:
                print("⚠️ _auto_finalize: invalid secret — ignored")
                return "ok", 200
            handle_auto_finalize(int(info["user_id"]), int(info["chat_id"]))
            return "ok", 200

        # Telegram webhook requests must pass secret check
        if WEBHOOK_SECRET:
            token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if token != WEBHOOK_SECRET:
                print("⚠️ Webhook secret mismatch — rejected")
                return "ok", 200  # 200 so Telegram doesn't retry; attacker gets no info

        print("📥 Payload:", json.dumps(data, indent=2))

        message = data.get("message")
        if not message:
            return "ok", 200

        chat_type = message.get("chat", {}).get("type")
        if chat_type in ("group", "supergroup"):
            handle_group_message(message)
        elif chat_type == "private":
            handle_private_message(message)

    except Exception as e:
        print(f"🔥 Unexpected error: {e}")
        traceback.print_exc()

    return "ok", 200


def telegram_asana_webhook(request):
    return _handle_webhook(request)


def it_support_webhook(request):
    return _handle_webhook(request)
