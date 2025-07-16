import os
import json
import requests
from flask import Flask, request

app = Flask(__name__)

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

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    message = data.get("message")
    if not message:
        return "ok"

    if "reply_to_message" in message and "text" in message["reply_to_message"]:
        original = message["reply_to_message"]
        question = original["text"]
        user = original["from"]["first_name"]
        group = message["chat"].get("title", "Private Chat")

        if create_asana_task(question, user, group):
            reply_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(reply_url, json={
                "chat_id": message["chat"]["id"],
                "reply_to_message_id": message["message_id"],
                "text": "✅ Added to Asana support board!"
            })

    return "ok"

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
    # app.run(debug=True, port=8080)