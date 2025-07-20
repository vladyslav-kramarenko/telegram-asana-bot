#!/bin/bash

echo "🚀 Deploying Cloud Function..."
gcloud functions deploy telegram_asana_webhook \
  --runtime python310 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point telegram_asana_webhook \
  --env-vars-file env.yaml \
  --region=us-central1

echo "⏳ Waiting a few seconds for deployment..."
sleep 5

echo "🌐 Getting deployed function URL..."
URL=$(gcloud functions describe telegram_asana_webhook \
  --region=us-central1 \
  --format='value(serviceConfig.uri)')

if [[ -z "$URL" ]]; then
  echo "❌ Failed to retrieve function URL"
  exit 1
fi

echo "✅ Function URL: $URL"

echo "🔗 Setting Telegram webhook..."
# Get token from the yaml file to ensure it's correct
TELEGRAM_TOKEN=$(grep 'TELEGRAM_TOKEN:' env.yaml | awk '{print $2}' | tr -d '"')
RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook?url=$URL")
echo "$RESPONSE" | jq

# Check webhook info
echo "📡 Verifying current Telegram webhook..."
curl -s "https://api.telegram.org/bot$TELEGRAM_TOKEN/getWebhookInfo" | jq

echo "🎉 Done!"