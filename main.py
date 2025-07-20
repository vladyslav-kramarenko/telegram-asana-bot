import os
import json
import requests

# --- Configuration ---
# These are loaded from the Google Cloud Function's environment variables.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ASANA_TOKEN = os.environ.get("ASANA_TOKEN")
ASANA_PROJECT_ID = os.environ.get("ASANA_PROJECT_ID")

# Whitelist of user IDs who can create tasks in private chats.
# This should be a comma-separated string of numbers, e.g., "12345678,87654321"
ALLOWED_USER_IDS_STR = os.environ.get("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS_STR.split(',') if uid.strip()]

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
        # 1. Get file path from Telegram
        print(f"Getting file path for file_id: {file_id}")
        get_file_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile"
        file_response = requests.get(get_file_url, params={"file_id": file_id})
        file_response.raise_for_status()
        file_path = file_response.json()["result"]["file_path"]
        file_name = file_path.split('/')[-1]

        # 2. Get the full download URL for the file
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        # 3. Determine the correct MIME type for the image
        content_type = 'application/octet-stream' # Default
        if file_name.lower().endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        elif file_name.lower().endswith('.png'):
            content_type = 'image/png'
        
        # 4. Stream the download from Telegram and upload to Asana simultaneously
        print(f"Streaming {file_name} as {content_type} to Asana task {task_gid}")
        with requests.get(download_url, stream=True) as image_response:
            image_response.raise_for_status()
            
            attachment_url = f"https://app.asana.com/api/1.0/tasks/{task_gid}/attachments"
            headers = { "Authorization": f"Bearer {ASANA_TOKEN}" }
            files = {
                'file': (file_name, image_response.raw, content_type)
            }
            
            upload_response = requests.post(attachment_url, headers=headers, files=files)
            upload_response.raise_for_status()

        print("✅ Successfully attached image to Asana task.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED to attach image to Asana. Error: {e}")
        if e.response is not None:
            print(f"API Response Text: {e.response.text}")
        return False
    except KeyError:
        print("❌ FAILED to parse Telegram file API response.")
        return False

def send_telegram_confirmation(chat_id, message_id, asana_response):
    """Sends a success confirmation message back to Telegram."""
    task_url = asana_response.get("data", {}).get("permalink_url", "")
    
    reply_text = "✅ Task created in Asana!"
    if task_url:
        reply_text += f"\n[View Task]({task_url})"

    print("✅ Sending confirmation to Telegram.")
    reply_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    requests.post(reply_url, json={
        "chat_id": chat_id,
        "reply_to_message_id": message_id,
        "text": reply_text,
        "parse_mode": "Markdown"
    })

def send_telegram_error_reply(chat_id, message_id, error_text):
    """Sends a user-facing error message back to Telegram."""
    print(f"⚠️ Sending error reply to user: {error_text}")
    reply_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(reply_url, json={
        "chat_id": chat_id,
        "reply_to_message_id": message_id,
        "text": f"⚠️ {error_text}"
    })

def parse_message(message):
    """
    Parses a message and returns a tuple: (status, data).
    Status can be "success", "error", or "ignore".
    Data is a dict for success, or a string for error/ignore.
    """
    chat_info = message.get("chat", {})
    chat_type = chat_info.get("type")
    
    # --- Handler for Group/Supergroup Messages ---
    if chat_type in ["group", "supergroup"]:
        
        # First, check if the bot was mentioned in the message text.
        is_bot_mentioned = False
        entities = message.get("entities", [])
        for entity in entities:
            if entity.get("type") == "mention":
                is_bot_mentioned = True
                break
        
        if not is_bot_mentioned:
            return ("ignore", "Bot was not mentioned in this message.")

        # --- Bot was mentioned. Now, is it a reply or a standalone message? ---
        
        # CASE 1: It's a reply to another message.
        if 'reply_to_message' in message:
            print("🕵️ Parsing group reply mention.")
            original_message = message.get("reply_to_message")
            
            reply_comment = message.get("text", "")
            mentions_to_remove = [reply_comment[e.get("offset"):e.get("offset")+e.get("length")] for e in entities if e.get("type") == "mention"]
            for mention in set(mentions_to_remove):
                reply_comment = reply_comment.replace(mention, "").strip()

            original_author_info = original_message.get("from", {})
            original_text = original_message.get("text") or original_message.get("caption")

            original_content_description = original_text
            photo_file_id = None
            if not original_content_description:
                if "photo" in original_message:
                    original_content_description = "[Image attached to task]"
                    photo_file_id = original_message["photo"][-1].get("file_id")
                else:
                    original_content_description = ""
            elif "photo" in original_message:
                 photo_file_id = original_message["photo"][-1].get("file_id")

            if not reply_comment and not original_content_description:
                return ("error", "I can't create a task from this. Please add a comment in your reply, or reply to a message that contains text or a caption.")

            final_question_parts = []
            if reply_comment:
                final_question_parts.append(f"Comment: {reply_comment}")
            if original_content_description:
                final_question_parts.append(f"Original Content: {original_content_description}")
            
            final_question = "\n---\n".join(final_question_parts)
            
            task_details = {
                "question": final_question,
                "user": original_author_info.get("first_name", "Unknown User"),
                "group": chat_info.get("title", "Unknown Group"),
                "chat_id": chat_info.get("id"),
                "message_id": message.get("message_id"),
                "photo_file_id": photo_file_id
            }
            return ("success", task_details)

        # CASE 2: It's a standalone mention, not a reply.
        else:
            print("🕵️ Parsing standalone group mention.")
            author_info = message.get("from", {})
            
            question = message.get("text", "")
            mentions_to_remove = [question[e.get("offset"):e.get("offset")+e.get("length")] for e in entities if e.get("type") == "mention"]
            for mention in set(mentions_to_remove):
                question = question.replace(mention, "").strip()

            photo_file_id = None
            if "photo" in message:
                photo_file_id = message["photo"][-1].get("file_id")
                if not question:
                    question = "[Image attached to task]"
            
            if not question:
                return ("error", "Please mention me with some text or an image.")

            task_details = {
                "question": question,
                "user": author_info.get("first_name", "Unknown User"),
                "group": chat_info.get("title", "Unknown Group"),
                "chat_id": chat_info.get("id"),
                "message_id": message.get("message_id"),
                "photo_file_id": photo_file_id
            }
            return ("success", task_details)

    # --- Handler for Private Chats (Direct Messages & Forwards) ---
    elif chat_type == "private":
        print("🕵️ Parsing private message.")
        author_info = message.get("from", {})
        user_id = author_info.get("id")
        
        print(f"  - User ID from message: {user_id}")
        print(f"  - Whitelist: {ALLOWED_USER_IDS}")

        if not user_id or user_id not in ALLOWED_USER_IDS:
            print(f"🚫 User {user_id} is not whitelisted.")
            return ("error", "Sorry, you are not authorized to create tasks.")
        
        print("  - User is whitelisted.")
        question = message.get("text") or message.get("caption")
        photo_file_id = None
        
        if "photo" in message:
            photo_file_id = message["photo"][-1].get("file_id")
            if not question:
                question = "[Image attached to task]"
        
        forward_info = message.get("forward_origin")
        if forward_info and not question:
            question = "[Forwarded Media]"

        if not question:
            return ("error", "Please send a text message, a forward, or media with a caption.")

        task_details = {
            "question": question,
            "user": author_info.get("first_name", "Unknown User"),
            "group": "Private Chat",
            "chat_id": chat_info.get("id"),
            "message_id": message.get("message_id"),
            "photo_file_id": photo_file_id
        }
        return ("success", task_details)
        
    return ("ignore", "Unsupported chat type.")

def telegram_asana_webhook(request):
    """Main webhook handler for all Telegram updates."""
    if not TELEGRAM_TOKEN:
        print("FATAL: TELEGRAM_TOKEN environment variable not set.")
        return "Configuration error", 500

    try:
        data = request.get_json()
        if not data:
            return "Bad Request", 400

        print("📥 Raw payload:", json.dumps(data, indent=2))

        message = data.get("message")
        if not message:
            return "ok", 200
        
        status, result = parse_message(message)

        if status == "success":
            task_details = result
            print(f"📋 Parsed Task: {task_details}")
            
            # Create the main task with text
            success, asana_task_object = create_asana_task(task_details)
            
            if success:
                # If there's an image, try to attach it
                photo_file_id = task_details.get("photo_file_id")
                task_gid = asana_task_object.get("data", {}).get("gid")

                if photo_file_id and task_gid:
                    attach_image_to_asana_task(task_gid, photo_file_id)

                # Send confirmation to the user
                send_telegram_confirmation(
                    task_details["chat_id"], 
                    task_details["message_id"], 
                    asana_task_object
                )
            else: # If Asana task creation fails, tell the user.
                send_telegram_error_reply(
                    task_details["chat_id"],
                    task_details["message_id"],
                    "Could not create a task in Asana. Please check the logs."
                )

        elif status == "error":
            error_message = result
            chat_id = message.get("chat", {}).get("id")
            message_id = message.get("message_id")
            if chat_id and message_id:
                send_telegram_error_reply(chat_id, message_id, error_message)
        else: # status == "ignore"
            print(f"✅ Message ignored: {result}")

    except Exception as e:
        print(f"🔥🔥🔥 An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

    return "ok", 200
