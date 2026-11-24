#!/usr/bin/env bash
# Cron entry point. Cron has a minimal environment, so everything is set here.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a
exec .venv/bin/harvest --verbose run >> harvest.log 2>&1
