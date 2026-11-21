#!/usr/bin/env bash
# Демонстрация: загрузка, открытие/закрытие сессии, тесты, результаты -> demo/report.html
#   bash deploy/demo.sh [--offline] [--skip-tests]
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT"
exec "$VENV/bin/python" demo/run_demo.py "$@"
