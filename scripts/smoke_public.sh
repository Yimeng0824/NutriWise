#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:?Usage: scripts/smoke_public.sh your.domain.example}"
BASE="https://${DOMAIN}"

echo "[1/4] healthz"
curl --fail --silent --show-error "${BASE}/healthz" | grep -q '"status":"ok"'

echo "[2/4] readyz (loads BGE/FAISS on first call)"
curl --fail --silent --show-error --max-time 240 "${BASE}/readyz" | grep -q '"status":"ok"'

echo "[3/4] student route"
curl --fail --silent --show-error "${BASE}/student/" >/dev/null

echo "[4/4] teacher route"
curl --fail --silent --show-error "${BASE}/teacher/" >/dev/null

echo "Public smoke test passed: ${BASE}"
