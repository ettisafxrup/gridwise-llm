#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT:-$1}}"
REQUEST_FILE="tests/sample_request.json"

if [[ ! -f "$REQUEST_FILE" ]]; then
  echo "Missing request file: $REQUEST_FILE" >&2
  exit 1
fi

echo "Testing $BASE_URL"
echo

echo "1. Health check"
curl.exe --fail-with-body -sS -i \
  "$BASE_URL/health"

echo
echo "2. Optimization request"
curl.exe --fail-with-body -sS -i \
  -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  --data-binary "@$REQUEST_FILE"

echo
echo "3. Status-only check"
curl.exe --fail-with-body -sS \
  -o response.json \
  -w "HTTP status: %{http_code}\n" \
  -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  --data-binary "@$REQUEST_FILE"

echo "Saved response to response.json"

echo
echo "4. Expected validation failure"
curl.exe -sS -i \
  -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  --data '{"scenario_id":"TEST"}'