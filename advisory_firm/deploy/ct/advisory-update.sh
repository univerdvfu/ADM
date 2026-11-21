#!/usr/bin/env bash
set -euo pipefail
APP=/opt/advisory_firm
BRANCH=main

before=$(runuser -u advisory -- git -C "$APP" rev-parse HEAD)
runuser -u advisory -- git -C "$APP" fetch --quiet origin "$BRANCH"
runuser -u advisory -- git -C "$APP" merge --ff-only "origin/$BRANCH"
after=$(runuser -u advisory -- git -C "$APP" rev-parse HEAD)

if [ "$before" != "$after" ]; then
    runuser -u advisory -- /home/advisory/advisory-stack/venv/bin/python -m compileall -q "$APP/analytics_firm" "$APP/service"
    systemctl restart advisory-service advisory-airflow advisory-airflow-web
    echo "Обновлено $before → $after, службы перезапущены"
fi
