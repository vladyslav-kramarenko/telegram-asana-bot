#!/bin/bash

set -a
source .env
set +a

gcloud functions deploy telegram_asana_webhook \
  --runtime python310 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point app \
  --set-env-vars TELEGRAM_TOKEN=$TELEGRAM_TOKEN,ASANA_TOKEN=$ASANA_TOKEN,ASANA_PROJECT_ID=$ASANA_PROJECT_ID \
  --region=us-central1