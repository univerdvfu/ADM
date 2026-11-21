#!/usr/bin/env bash
# Запуск сервисов (только 127.0.0.1) и подготовка баз.   bash deploy/start.sh
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$HOME_DIR"
mkdir -p data/clickhouse data/minio logs

if ! curl -fs "http://${CH_HOST}:${CH_PORT}/ping" >/dev/null 2>&1; then
  (nohup bin/clickhouse server -- --path="$HOME_DIR/data/clickhouse" \
      --http_port="$CH_PORT" --listen_host=127.0.0.1 > logs/clickhouse.log 2>&1 &)
fi

if ! curl -fs "http://${MINIO_ENDPOINT}/minio/health/live" >/dev/null 2>&1; then
  (MINIO_ROOT_USER=$MINIO_USER MINIO_ROOT_PASSWORD=$MINIO_PASSWORD nohup bin/minio server \
      data/minio --address "$MINIO_ENDPOINT" --console-address 127.0.0.1:39011 \
      > logs/minio.log 2>&1 &)
fi

# PostgreSQL: pgserver запускает настоящий PostgreSQL 16 и оставляет его работать
"$VENV/bin/python" - <<PY
import pgserver, psycopg2
srv = pgserver.get_server("$PG_DATA", cleanup_mode=None)
c = psycopg2.connect(srv.get_uri()); c.autocommit = True
cur = c.cursor(); cur.execute("SELECT 1 FROM pg_database WHERE datname='advisory'")
if not cur.fetchone():
    cur.execute("CREATE DATABASE advisory")
print("PostgreSQL:", srv.get_uri())
PY

for i in $(seq 1 30); do
  curl -fs "http://${CH_HOST}:${CH_PORT}/ping" >/dev/null 2>&1 && break; sleep 1
done
curl -fs "http://${CH_HOST}:${CH_PORT}/ping" && curl -fs "http://${MINIO_ENDPOINT}/minio/health/live" \
  && echo "ClickHouse, MinIO, PostgreSQL запущены"

"$VENV/bin/airflow" db migrate >/dev/null 2>&1 || true
echo "Airflow: bash deploy/airflow.sh  (веб-интерфейс на http://127.0.0.1:8080)"
