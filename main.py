import os
import json
import requests

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ASANA_TOKEN = os.environ.get("ASANA_TOKEN")
ASANA_PROJECT_ID = os.environ.get("ASANA_PROJECT_ID")

def create_asana_task(question, user, group):
    """Creates a task in Asana and returns the result."""
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
            "name": f"Support Question from {user} in '{group}'",
            "notes": f"Question:\n{question}\n\nAsked by: {user}\nGroup: {group}"
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


def telegram_asana_webhook(request):
    """Main webhook handler for Telegram updates."""
    if not TELEGRAM_TOKEN:
        print("FATAL: TELEGRAM_TOKEN environment variable not set. Function cannot proceed.")
        return "Configuration error", 500

    try:
        data = request.get_json()
        if not data:
            print("⚠️ Received an empty or non-JSON request.")
            return "Bad Request", 400

        print("📥 Raw payload:", json.dumps(data, indent=2))

        message = data.get("message")
        if not message:
            print("✅ Payload received, but it's not a message. Ignoring.")
            return "ok", 200

        original_message = message.get("reply_to_message")
        if not original_message:
            print("⚠️ Message was not a reply. Ignoring.")
            return "ok", 200

        question = original_message.get("text")
        if not question:
            print("⚠️ Replied-to message has no text. Ignoring.")
            return "ok", 200

        author_info = original_message.get("from", {})
        user = author_info.get("first_name", "Unknown User")

        chat_info = message.get("chat", {})
        group = chat_info.get("title", "Private Chat")
        chat_id = chat_info.get("id")
        
        if not chat_id:
            print("❌ Could not determine chat_id. Cannot reply.")
            return "Error processing request", 400

        print(f"📋 Parsed:\n- Question: {question}\n- User: {user}\n- Group: {group}")

        success, result = create_asana_task(question, user, group)

        if success:
            task_url = result.get("data", {}).get("permalink_url", "")
            
            # Construct a more helpful reply message
            reply_text = "✅ Task created in Asana!"
            if task_url:
                reply_text += f"\n[View Task]({task_url})"

            print("✅ Sending confirmation to Telegram.")
            reply_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            reply_to_id = message.get("message_id") 

            r = requests.post(reply_url, json={
                "chat_id": chat_id,
                "reply_to_message_id": reply_to_id,
                "text": reply_text,
                "parse_mode": "Markdown" # Needed for the link to work
            })
            print("📨 Telegram reply status:", r.status_code)
        else:
            print("❌ Asana task creation failed. See logs above.")
            # Optionally, send an error message back to the user
            # (be careful not to spam in case of a persistent error)

    except Exception as e:
        print(f"🔥🔥🔥 An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

    return "ok", 200