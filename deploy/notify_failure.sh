#!/usr/bin/env bash
# Telegram alert when a pr-shopper unit fails. Wired via OnFailure= drop-ins.
# Uses the forja profile bot (read-only usage of its token; the gateway is untouched).
set -uo pipefail

UNIT="${1:-unknown unit}"
ENV_FILE="$HOME/.hermes/profiles/forja/.env"

TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
CHAT_ID="$(grep -E '^TELEGRAM_ALLOWED_USERS=' "$ENV_FILE" | cut -d= -f2- | cut -d, -f1)"

if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
  echo "notify_failure: missing TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USERS in $ENV_FILE" >&2
  exit 0  # never fail the caller because alerting broke
fi

STATUS="$(systemctl --user show "$UNIT" -p ExecMainStatus -p Result --value 2>/dev/null | tr '\n' ' ')"
MSG="PLAZA-PR alert: ${UNIT} FAILED on $(hostname) at $(date '+%Y-%m-%d %H:%M %Z'). Status: ${STATUS}. Check: journalctl --user -u ${UNIT} -n 50"

curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${MSG}" > /dev/null || true
