#!/bin/bash

FUNCTION_NAME="telegram_asana_webhook"
CONFIG_FILE="configs/env.yaml"
PROJECT_ID=$(grep '^PROJECT_ID:' ${CONFIG_FILE} | awk '{print $2}' | tr -d '"')

[ -n "$PROJECT_ID" ] || { echo "❌ PROJECT_ID missing in ${CONFIG_FILE}"; exit 1; }

echo "🚀 Deploying ${FUNCTION_NAME} to project ${PROJECT_ID}..."
gcloud functions deploy ${FUNCTION_NAME} \
  --project=${PROJECT_ID} \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point telegram_asana_webhook \
  --env-vars-file ${CONFIG_FILE} \
  --max-instances 3 \
  --region=us-central1

echo "⏳ Waiting a few seconds for deployment..."
sleep 5

echo "🌐 Getting deployed function URL..."
URL=$(gcloud functions describe ${FUNCTION_NAME} \
  --project=${PROJECT_ID} \
  --region=us-central1 \
  --format='value(serviceConfig.uri)')

if [[ -z "$URL" ]]; then
  echo "❌ Failed to retrieve function URL"
  exit 1
fi

echo "✅ Function URL: $URL"

echo "🔗 Setting Telegram webhook..."
TELEGRAM_TOKEN=$(grep 'TELEGRAM_TOKEN:' ${CONFIG_FILE} | awk '{print $2}' | tr -d '"')
WEBHOOK_SECRET=$(grep 'WEBHOOK_SECRET:' ${CONFIG_FILE} | awk '{print $2}' | tr -d '"')
RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook" \
  --data-urlencode "url=$URL" \
  --data-urlencode "secret_token=$WEBHOOK_SECRET")
echo "$RESPONSE" | jq

echo "📡 Verifying current Telegram webhook..."
curl -s "https://api.telegram.org/bot$TELEGRAM_TOKEN/getWebhookInfo" | jq

echo "🎉 Done!"
