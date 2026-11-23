#!/usr/bin/env bash
# Walks through a reservation lifecycle against a running API (default http://localhost:5080).
set -euo pipefail
BASE="${BASE:-http://localhost:5080}"

token() {
  curl -s -X POST "$BASE/auth/token" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" | jq -r .accessToken
}
PLANNER=$(token planner.daventry planner-demo-pass)
PICKER=$(token picker.manchester picker-demo-pass)
ADMIN=$(token ops.admin admin-demo-pass)
auth() { echo "Authorization: Bearer $1"; }

echo "== Stock below reorder point at Daventry (first 3)"
curl -s "$BASE/api/stock?warehouse=DIR1&belowReorder=true&pageSize=3" -H "$(auth "$PLANNER")" \
  | jq -c '{totalCount, items: [.items[] | {sku, onHand, reserved, available, reorderPoint}]}'

echo "== Reserve 2 lines for order ORD-10001 (Idempotency-Key: demo-ord-10001)"
BODY='{"orderReference":"ORD-10001","warehouseCode":"DIR1","lines":[{"sku":"KIT-00007","quantity":5},{"sku":"GDN-00002","quantity":2}]}'
curl -s -i -X POST "$BASE/api/reservations" -H "$(auth "$PLANNER")" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-ord-10001' -d "$BODY" | grep -iE '^(HTTP|location|idempotent-replayed)' | tr -d '\r'
echo "== Same request again (network retry)"
RES=$(curl -s -i -X POST "$BASE/api/reservations" -H "$(auth "$PLANNER")" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-ord-10001' -d "$BODY")
echo "$RES" | grep -iE '^(HTTP|idempotent-replayed)' | tr -d '\r'
ID=$(echo "$RES" | tail -1 | jq -r .id)

echo "== Same key, different body"
curl -s -X POST "$BASE/api/reservations" -H "$(auth "$PLANNER")" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-ord-10001' \
  -d '{"orderReference":"ORD-10001","warehouseCode":"DIR1","lines":[{"sku":"KIT-00007","quantity":9}]}' | jq -c '{status, code, detail}'

echo "== Ask for more than is available"
curl -s -X POST "$BASE/api/reservations" -H "$(auth "$PLANNER")" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-ord-10002' \
  -d '{"orderReference":"ORD-10002","warehouseCode":"DIR1","lines":[{"sku":"KIT-00007","quantity":9000}]}' | jq -c '{status, code, detail}'

echo "== Picker tries to create a reservation (wrong role)"
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BASE/api/reservations" -H "$(auth "$PICKER")" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-ord-10003' -d "$BODY"

echo "== Picker confirms the pick"
curl -s -X POST "$BASE/api/reservations/$ID/confirm" -H "$(auth "$PICKER")" | jq -c '{status, totalUnits, lines}'

echo "== Ledger for KIT-00007"
curl -s "$BASE/api/stock/DIR1/KIT-00007/movements" -H "$(auth "$PLANNER")" \
  | jq -c '.items[] | {type, quantity, onHandAfter, reservedAfter, actor}'

sleep 3
echo "== Outbox after the background publisher ran"
curl -s "$BASE/api/ops/outbox" -H "$(auth "$ADMIN")" | jq -c .
echo "== Valuation (GBP)"
curl -s "$BASE/api/stock/valuation" -H "$(auth "$ADMIN")" | jq -c '.[]'
echo "== Ledger reconciliation"
curl -s "$BASE/api/ops/reconcile" -H "$(auth "$ADMIN")" | jq -c .
