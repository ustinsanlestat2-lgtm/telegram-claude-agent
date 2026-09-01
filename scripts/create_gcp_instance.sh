#!/usr/bin/env bash
# Creates the GCP VM that will host the Telegram <-> Claude Code bot.
# No public IP: the bot only needs outbound access (Telegram long-polling,
# GitHub, Anthropic), so there's no reason to expose an inbound port.
# You'll reach the VM via IAP tunneling (gcloud compute ssh --tunnel-through-iap).
set -euo pipefail

# ---- EDIT THESE ----
PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
ZONE="us-central1-a"
INSTANCE_NAME="agent-bot"
MACHINE_TYPE="e2-small"
# ---------------------

gcloud config set project "$PROJECT_ID"

# Make sure IAP-based SSH is allowed (idempotent if it already exists).
gcloud compute firewall-rules create allow-iap-ssh \
  --direction=INGRESS \
  --action=allow \
  --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 \
  --network=default \
  2>/dev/null || echo "Firewall rule allow-iap-ssh already exists, skipping."

gcloud compute instances create "$INSTANCE_NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --no-address \
  --shielded-secure-boot \
  --shielded-vtpm \
  --shielded-integrity-monitoring

echo
echo "Instance created with no public IP."
echo "Connect with:"
echo "  gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --tunnel-through-iap"
