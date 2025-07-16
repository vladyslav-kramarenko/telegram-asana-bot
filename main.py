import os
import json
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ASANA_TOKEN = os.environ["ASANA_TOKEN"]
ASANA_PROJECT_ID = os.environ["ASANA_PROJECT_ID"]

def create_asana_task(question, user, group):
    url = "https://app.asana.com/api/1.0/tasks"
    headers = {
        "Authorization": f"Bearer {ASANA_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "data": {
            "projects": [ASANA_PROJECT_ID],
            "name": f"Support Question from {user}",
            "notes": f"Question:\n{question}\n\nAsked by: {user}\nGroup: {group}"
        }
    }
    response = requests.post(url, headers=headers, json=data)
    return response.ok

def telegram_asana_webhook(request):
    data = request.get_json()
    print("📥 Raw payload:", json.dumps(data, indent=2))  # LOG EVERYTHING

    message = data.get("message")
    if not message:
        print("⚠️ No 'message' in payload.")
        return "ok"

    print("✅ Message received:", message)

    if "reply_to_message" in message and "text" in message["reply_to_message"]:
        original = message["reply_to_message"]
        question = original["text"]
        user = original["from"]["first_name"]
        group = message["chat"].get("title", "Private Chat")

        print(f"📋 Parsed:\n- Question: {question}\n- User: {user}\n- Group: {group}")

        if create_asana_task(question, user, group):
            print("✅ Task sent to Asana!")
            reply_url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
            r = requests.post(reply_url, json={
                "chat_id": message["chat"]["id"],
                "reply_to_message_id": message["message_id"],
                "text": "✅ Added to Asana support board!"
            })
            print("📨 Telegram reply:", r.status_code, r.text)
        else:
            print("❌ Asana task creation failed.")

    else:
        print("⚠️ Message was not a reply or didn't include text.")

    return "ok"