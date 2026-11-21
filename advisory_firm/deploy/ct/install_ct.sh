#!/usr/bin/env bash
# Запускать от root внутри контейнера после deploy/setup.sh (от пользователя advisory).
set -euo pipefail
APP=/opt/advisory_firm; H=/home/advisory/advisory-stack; V=$H/venv/bin
# иначе logind при выходе сессии удаляет POSIX-сегменты PostgreSQL из /dev/shm
mkdir -p /etc/systemd/logind.conf.d; printf '[Login]
RemoveIPC=no
' > /etc/systemd/logind.conf.d/advisory.conf; systemctl restart systemd-logind
ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime; echo Europe/Moscow > /etc/timezone

if [ ! -f "$H/secrets.env" ]; then
  M=$(openssl rand -hex 12); W=$(openssl rand -hex 8)
  printf 'MINIO_ROOT_USER=advisory\nMINIO_ROOT_PASSWORD=%s\nMINIO_USER=advisory\nMINIO_PASSWORD=%s\n' "$M" "$M" > "$H/secrets.env"
  chown advisory:advisory "$H/secrets.env"; chmod 600 "$H/secrets.env"
  printf 'web user: advisory\nweb password: %s\n' "$W" > /root/advisory-credentials.txt; chmod 600 /root/advisory-credentials.txt
  htpasswd -bc /etc/nginx/advisory.htpasswd advisory "$W" 2>/dev/null
fi

install -d -o advisory -g advisory -m 700 "$H/data/clickhouse" "$H/data/minio" "$H/logs" "$H/run"
cp "$APP"/deploy/ct/advisory-*.service /etc/systemd/system/
cp "$APP"/deploy/ct/nginx-advisory.conf /etc/nginx/sites-available/advisory
ln -sf /etc/nginx/sites-available/advisory /etc/nginx/sites-enabled/advisory
rm -f /etc/nginx/sites-enabled/default
systemctl daemon-reload
systemctl enable --now advisory-postgres advisory-clickhouse advisory-minio

for i in $(seq 1 60); do curl -fs http://127.0.0.1:8123/ping >/dev/null 2>&1 && break; sleep 1; done
# общая база service: в неё пишет DAG и из неё читает веб-сервис
su advisory -c "PG_DATA=$H/pgdata $V/python - <<'PY'
import os, pgserver, psycopg2
srv = pgserver.get_server(os.environ['PG_DATA'], cleanup_mode=None)
c = psycopg2.connect(srv.get_uri()); c.autocommit = True
cur = c.cursor(); cur.execute(\"SELECT 1 FROM pg_database WHERE datname='service'\")
if not cur.fetchone():
    cur.execute('CREATE DATABASE service')
print('база service готова (в ней работают и DAG, и веб-сервис)')
PY"

systemctl enable --now advisory-service advisory-airflow
nginx -t && systemctl enable nginx && systemctl restart nginx
systemctl --no-pager --type=service list-units 'advisory-*' nginx.service | cat
