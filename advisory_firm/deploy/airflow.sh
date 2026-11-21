#!/usr/bin/env bash
# Airflow.
#   bash deploy/airflow.sh test 2026-10-29   разовый прогон каждой задачи DAG (проверено)
#   bash deploy/airflow.sh standalone        планировщик + веб-интерфейс (не проверялся)
set -euo pipefail
source "$(dirname "$0")/env.sh"
AF="$VENV/bin/airflow"
case "${1:-test}" in
  test)
    DAY="${2:-$(date +%F)}"
    for t in init fetch load check recommend; do
      echo "== $t"; "$AF" tasks test advisory_pipeline "$t" "$DAY" 2>&1 \
        | grep -E "Done. Returned|Marking task|Error|Traceback" | cut -c1-240
      # клиентов фирмы создаёт человек; без них recommend вернёт 0
      if [ "$t" = init ]; then
        "$VENV/bin/python" - <<'PY'
import os, psycopg2
c = psycopg2.connect(os.environ["PG_DSN"]); cur = c.cursor()
cur.execute("SELECT count(*) FROM advisory_clients")
if cur.fetchone()[0] == 0:
    cur.execute("INSERT INTO advisory_clients VALUES (1,'client-A','conservative',365,30,'active'),"
                "(2,'client-B','aggressive',90,100,'active')")
    c.commit(); print("демо-клиенты добавлены")
PY
      fi
    done ;;
  standalone) exec "$AF" standalone ;;
  *) echo "usage: $0 test [YYYY-MM-DD] | standalone"; exit 2 ;;
esac
