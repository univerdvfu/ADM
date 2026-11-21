#!/usr/bin/env bash
# Сервис просмотра БД и тестов: http://127.0.0.1:8765 (слушает только localhost).
#   bash deploy/service.sh        (сервисы должны быть запущены: bash deploy/start.sh)
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT"
exec "$VENV/bin/python" service/app.py
