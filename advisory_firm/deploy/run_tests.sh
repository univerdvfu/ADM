#!/usr/bin/env bash
# Тесты (нужны запущенные сервисы: bash deploy/start.sh).   bash deploy/run_tests.sh [pytest-аргументы]
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT"
exec "$VENV/bin/python" -m pytest -q "$@"
