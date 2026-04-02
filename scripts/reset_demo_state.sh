#!/usr/bin/env bash
set -euo pipefail

EVENT_SERVICE_URL="${EVENT_SERVICE_URL:-http://localhost:5003}"
SEAT_INVENTORY_URL="${SEAT_INVENTORY_URL:-http://localhost:5004}"
USER_SERVICE_URL="${USER_SERVICE_URL:-http://localhost:5001}"
PURCHASE_SERVICE_URL="${PURCHASE_SERVICE_URL:-http://localhost:5010}"
TICKET_SERVICE_URL="${TICKET_SERVICE_URL:-http://localhost:5002}"
NOTIFICATION_SERVICE_URL="${NOTIFICATION_SERVICE_URL:-http://localhost:5013}"

post_with_retry() {
    local url="$1"
    local max_attempts="${2:-20}"
    local sleep_seconds="${3:-1}"
    local attempt=1
    while true; do
        if curl -fsS -X POST "${url}" >/dev/null; then
            return 0
        fi
        if [[ "${attempt}" -ge "${max_attempts}" ]]; then
            echo "[reset] failed after ${attempt} attempts: ${url}" >&2
            return 1
        fi
        attempt=$((attempt + 1))
        sleep "${sleep_seconds}"
    done
}

echo "[reset] resetting demo events..."
post_with_retry "${EVENT_SERVICE_URL}/events/reset-demo"

echo "[reset] resetting seat inventory..."
post_with_retry "${SEAT_INVENTORY_URL}/inventory/reset-demo"

echo "[reset] resetting users + managed events + user tickets..."
post_with_retry "${USER_SERVICE_URL}/user/reset-demo"

echo "[reset] resetting purchase records..."
post_with_retry "${PURCHASE_SERVICE_URL}/purchase/reset-demo"

echo "[reset] resetting issued tickets..."
post_with_retry "${TICKET_SERVICE_URL}/tickets/reset-demo"

echo "[reset] clearing notification logs..."
post_with_retry "${NOTIFICATION_SERVICE_URL}/notifications/reset-demo"

echo "[reset] done. Demo state is now clean."
echo "[reset] fan login: User ID 1"
echo "[reset] manager login: User ID 2"
