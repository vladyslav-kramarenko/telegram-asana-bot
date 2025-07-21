import os
import json
import requests
import datetime

# --- Configuration ---
# These are loaded from the Google Cloud Function's environment variables.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ASANA_TOKEN = os.environ.get("ASANA_TOKEN")
ASANA_PROJECT_ID = os.environ.get("ASANA_PROJECT_ID")
DUE_DATE_DAYS_STR = os.environ.get("DUE_DATE_DAYS") # New: Days to set due date

# Whitelist of user IDs who can create tasks in private chats.
# This should be a comma-separated string of numbers, e.g., "12345678,87654321"
ALLOWED_USER_IDS_STR = os.environ.get("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS_STR.split(',') if uid.strip()]

# --- Global variable to cache the bot's username ---
BOT_USERNAME = None

def get_bot_username():
    """
    Fetches the bot's own username using the getMe method and caches it.
    This is crucial for multi-bot environments.
    """
    global BOT_USERNAME
    if BOT_USERNAME is None:
        print("🤖 Bot username not cached. Fetching from Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe"
        try:
            response = requests.get(url)
            response.raise_for_status()
            BOT_USERNAME = response.json()["result"]["username"]
            print(f"✅ Bot username is '@{BOT_USERNAME}'")
        except Exception as e:
            print(f"🔥🔥🔥 CRITICAL: Could not fetch bot username. Error: {e}")
            # In case of failure, we can't proceed reliably.
            BOT_USERNAME = "" # Set to empty to avoid repeated calls
    return BOT_USERNAME


def create_asana_task(task_details):
    """Creates a task in Asana from a dictionary of details."""
    question = task_details.get("question")
    user = task_details.get("user")
    group = task_details.get("group")

    if not all([ASANA_TOKEN, ASANA_PROJECT_ID]):
        print("❌ ERROR: Asana environment variables are not set correctly.")
        return False, "Configuration error: Missing Asana token or project ID."

    url = "https://app.asana.com/api/1.0/tasks"
    headers = {
        "Authorization": f"Bearer {ASANA_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "data": {
            "projects": [ASANA_PROJECT_ID],
            "name": f"Support Task from {user} in '{group}'",
            "notes": f"Task Details:\n{question}\n\nFrom: {user}\nSource: {group}"
        }
    }
    
    # NEW: Add due date if configured
    if DUE_DATE_DAYS_STR and DUE_DATE_DAYS_STR.isdigit():
        try:
            days_to_add = int(DUE_DATE_DAYS_STR)
            due_date = datetime.date.today() + datetime.timedelta(days=days_to_add)
            # Asana API uses 'due_on' for setting a date-only due date.
            data["data"]["due_on"] = due_date.isoformat()
            print(f"✅ Setting due date to {data['data']['due_on']}")
        except ValueError:
            print(f"⚠️ Invalid value for DUE_DATE_DAYS: {DUE_DATE_DAYS_STR}. Skipping due date.")

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        response_data = response.json()
        print(f"✅ Asana task created successfully: {response_data}")
        return True, response_data
    except requests.exceptions.RequestException as e:
        error_message = f"❌ FAILED to create Asana task. Error: {e}"
        if e.response is not None:
            error_message += f" | Asana API Response: {e.response.text}"
        print(error_message)
        return False, error_message

def attach_image_to_asana_task(task_gid, file_id):
    """Downloads an image from Telegram and attaches it to an Asana task."""
    try:
        print(f"Getting file path for file_id: {file_id}")
        get_file_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile"
        file_response = requests.get(get_file_url, params={"file_id": file_id})
        file_response.raise_for_status()
        file_path = file_response.json()["result"]["file_path"]
        file_name = file_path.split('/')[-1]

        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        content_type = 'application/octet-stream'
        if file_name.lower().endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        elif file_name.lower().endswith('.png'):
            content_type = 'image/png'
        
        print(f"Streaming {file_name} as {content_type} to Asana task {task_gid}")
        with requests.get(download_url, stream=True) as image_response:
            image_response.raise_for_status()
            
            attachment_url = f"https://app.asana.com/api/1.0/tasks/{task_gid}/attachments"
            headers = { "Authorization": f"Bearer {ASANA_TOKEN}" }
            files = { 'file': (file_name, image_response.raw, content_type) }
            
            upload_response = requests.post(attachment_url, headers=headers, files=files)
            upload_response.raise_for_status()

        print("✅ Successfully attached image to Asana task.")
        return True

    except Exception as e:
        print(f"❌ FAILED to attach image to Asana. Error: {e}")
        return False

def send_telegram_confirmation(chat_id, message_id, asana_response):
    """Sends a success confirmation message back to Telegram."""
    task_url = asana_response.get("data", {}).get("permalink_url", "")
    
    reply_text = "✅ Task created in Asana!"
    if task_url:
        reply_text += f"\n[View Task]({task_url})"

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
        "chat_id": chat_id, "reply_to_message_id": message_id,
        "text": reply_text, "parse_mode": "Markdown"
    })

def send_telegram_error_reply(chat_id, message_id, error_text):
    """Sends a user-facing error message back to Telegram."""
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
        "chat_id": chat_id, "reply_to_message_id": message_id,
        "text": f"⚠️ {error_text}"
    })

def parse_message(message):
    """
    Parses a message and returns a tuple: (status, data).
    """
    chat_info = message.get("chat", {})
    chat_type = chat_info.get("type")
    
    # --- Handler for Group/Supergroup Messages ---
    if chat_type in ["group", "supergroup"]:
        
        # SELF-AWARENESS CHECK: Was *this specific bot* mentioned?
        bot_username = get_bot_username()
        text = message.get("text", "")
        entities = message.get("entities", [])
        
        is_this_bot_mentioned = False
        for entity in entities:
            if entity.get("type") == "mention":
                mention = text[entity.get("offset") : entity.get("offset") + entity.get("length")]
                if mention == f"@{bot_username}":
                    is_this_bot_mentioned = True
                    break
        
        if not is_this_bot_mentioned:
            return ("ignore", f"Another bot was mentioned, not @{bot_username}.")

        # --- This bot was mentioned. Now, is it a reply or a standalone message? ---
        if 'reply_to_message' in message:
            print("🕵️ Parsing group reply mention.")
            original_message = message.get("reply_to_message")
            
            reply_comment = text
            mentions_to_remove = [reply_comment[e.get("offset"):e.get("offset")+e.get("length")] for e in entities if e.get("type") == "mention"]
            for mention in set(mentions_to_remove):
                reply_comment = reply_comment.replace(mention, "").strip()

            original_author_info = original_message.get("from", {})
            original_text = original_message.get("text") or original_message.get("caption")

            photo_file_id = None
            original_content_description = original_text
            if not original_content_description:
                if "photo" in original_message:
                    original_content_description = "[Image attached to task]"
                    photo_file_id = original_message["photo"][-1].get("file_id")
            elif "photo" in original_message:
                 photo_file_id = original_message["photo"][-1].get("file_id")

            if not reply_comment and not original_content_description:
                return ("error", "Please add a comment in your reply, or reply to a message that contains text or a caption.")

            final_question = f"Comment: {reply_comment}\n---\nOriginal Content: {original_content_description}" if reply_comment and original_content_description else reply_comment or original_content_description

            task_details = { "question": final_question, "user": original_author_info.get("first_name", "Unknown User"), "group": chat_info.get("title", "Unknown Group"), "chat_id": chat_info.get("id"), "message_id": message.get("message_id"), "photo_file_id": photo_file_id }
            return ("success", task_details)

        else: # Standalone mention
            print("🕵️ Parsing standalone group mention.")
            author_info = message.get("from", {})
            
            question = text
            mentions_to_remove = [question[e.get("offset"):e.get("offset")+e.get("length")] for e in entities if e.get("type") == "mention"]
            for mention in set(mentions_to_remove):
                question = question.replace(mention, "").strip()

            photo_file_id = None
            if "photo" in message:
                photo_file_id = message["photo"][-1].get("file_id")
                if not question: question = "[Image attached to task]"
            
            if not question:
                return ("error", "Please mention me with some text or an image.")

            task_details = { "question": question, "user": author_info.get("first_name", "Unknown User"), "group": chat_info.get("title", "Unknown Group"), "chat_id": chat_info.get("id"), "message_id": message.get("message_id"), "photo_file_id": photo_file_id }
            return ("success", task_details)

    # --- Handler for Private Chats (Direct Messages & Forwards) ---
    elif chat_type == "private":
        print("🕵️ Parsing private message.")
        author_info = message.get("from", {})
        user_id = author_info.get("id")
        
        if not user_id or user_id not in ALLOWED_USER_IDS:
            return ("error", "Sorry, you are not authorized to create tasks.")
        
        question = message.get("text") or message.get("caption")
        photo_file_id = None
        
        if "photo" in message:
            photo_file_id = message["photo"][-1].get("file_id")
            if not question: question = "[Image attached to task]"
        
        if message.get("forward_origin") and not question:
            question = "[Forwarded Media]"

        if not question:
            return ("error", "Please send a text message, a forward, or media with a caption.")

        task_details = { "question": question, "user": author_info.get("first_name", "Unknown User"), "group": "Private Chat", "chat_id": chat_info.get("id"), "message_id": message.get("message_id"), "photo_file_id": photo_file_id }
        return ("success", task_details)
        
    return ("ignore", "Unsupported chat type.")

def telegram_asana_webhook(request):
    """Main webhook handler for all Telegram updates."""
    if not TELEGRAM_TOKEN:
        print("FATAL: TELEGRAM_TOKEN environment variable not set.")
        return "Configuration error", 500
    
    # This ensures the bot knows its own name.
    get_bot_username()

    try:
        data = request.get_json()
        if not data: return "Bad Request", 400

        print("📥 Raw payload:", json.dumps(data, indent=2))

        message = data.get("message")
        if not message: return "ok", 200
        
        status, result = parse_message(message)

        if status == "success":
            task_details = result
            print(f"📋 Parsed Task: {task_details}")
            
            success, asana_task_object = create_asana_task(task_details)
            
            if success:
                photo_file_id = task_details.get("photo_file_id")
                task_gid = asana_task_object.get("data", {}).get("gid")
                if photo_file_id and task_gid:
                    attach_image_to_asana_task(task_gid, photo_file_id)
                send_telegram_confirmation(task_details["chat_id"], task_details["message_id"], asana_task_object)
            else:
                send_telegram_error_reply(task_details["chat_id"], task_details["message_id"], "Could not create a task in Asana. Please check the logs.")

        elif status == "error":
            send_telegram_error_reply(message.get("chat", {}).get("id"), message.get("message_id"), result)
        else: # status == "ignore"
            print(f"✅ Message ignored: {result}")

    except Exception as e:
        print(f"🔥�🔥 An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

    return "ok", 200