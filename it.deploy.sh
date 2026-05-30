#!/bin/bash

FUNCTION_NAME="it_support_webhook"
CONFIG_FILE="configs/env_it.yaml"

echo "🚀 Deploying ${FUNCTION_NAME}..."
gcloud functions deploy ${FUNCTION_NAME} \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point it_support_webhook \
  --env-vars-file ${CONFIG_FILE} \
  --max-instances 3 \
  --region=us-central1

echo "⏳ Waiting a few seconds for deployment..."
sleep 5

echo "🌐 Getting deployed function URL..."
URL=$(gcloud functions describe ${FUNCTION_NAME} \
  --region=us-central1 \
  --format='value(serviceConfig.uri)')

if [[ -z "$URL" ]]; then
  echo "❌ Failed to retrieve function URL"
  exit 1
fi

echo "✅ Function URL: $URL"
echo ""
echo "⚠️  If this is the first deploy, update GCF_URL in configs/env_it.yaml with the URL above, then run ./it.deploy.sh again."

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
