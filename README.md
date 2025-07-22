# Telegram to Asana Task Bot
A serverless Telegram bot that creates Asana tasks from group mentions or private messages. Built to support multiple, independent bot deployments from a single codebase.

## Core Features
* Flexible Task Creation: Create Asana tasks via direct mentions or replies in Telegram groups.
* Rich Content Support: Captures text, image attachments, and forwarded messages.
* Configurable Per Bot: Set unique Asana projects, due dates, and private-use whitelists for each deployed bot.
* Self-Aware: Prevents crosstalk between multiple bots in the same group by responding only to its own username.
* Serverless & Cost-Effective: Runs on the Google Cloud Functions free tier.

## How It Works
1. A user mentions the bot in Telegram.

2. A webhook triggers the bot's Google Cloud Function.

3. The Python script parses the message, formats the content, and checks its configuration.

4. The function calls the Asana API to create a task with the correct details, due date, and attachments.

5. The bot replies in Telegram with a confirmation and a link to the new task.
