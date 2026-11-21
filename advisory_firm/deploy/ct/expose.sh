#!/usr/bin/env bash
# Открывает доступ к PostgreSQL, ClickHouse и Airflow из сети контейнера (с паролями).
# Запускать от root внутри контейнера:  bash /opt/advisory_firm/deploy/ct/expose.sh <IP контейнера>
# Пароли пишутся в /root/advisory-credentials.txt (права 600).
set -euo pipefail
IP="${1:?укажите IP контейнера}"
NETS="${2:-10.50.16.0/24 10.53.16.0/24}"   # откуда разрешены подключения (через пробел)
APP=/opt/advisory_firm; H=/home/advisory/advisory-stack; V=$H/venv
PGBIN=$V/lib/python3.12/site-packages/pgserver/pginstall/bin
CRED=/root/advisory-credentials.txt

PGPW=$(openssl rand -hex 10); CHPW=$(openssl rand -hex 10); AFPW=$(openssl rand -hex 10)

# ---------- PostgreSQL: TCP + scram, роль только для чтения ----------
sed -i "s#^ExecStart=.*#ExecStart=$PGBIN/postgres -D $H/pgdata -k $H/pgdata -h 127.0.0.1,$IP#" /etc/systemd/system/advisory-postgres.service
HBA=$H/pgdata/pg_hba.conf
sed -i '/advisory-remote/,$d' "$HBA"
echo "# advisory-remote: подключения по сети только с паролем" >> "$HBA"
for n in $NETS; do printf 'host    all             advisory_ro     %s    scram-sha-256
' "$n" >> "$HBA"; done
systemctl daemon-reload
systemctl stop advisory-postgres advisory-service advisory-airflow 2>/dev/null || true
su advisory -c "$PGBIN/pg_ctl -D $H/pgdata -m fast stop" >/dev/null 2>&1 || true   # прежний сервер от pgserver
systemctl start advisory-postgres
for i in $(seq 1 30); do su advisory -c "$PGBIN/pg_isready -h $H/pgdata" >/dev/null 2>&1 && break; sleep 1; done
su advisory -c "PGPW=$PGPW $V/bin/python - <<'PY'
import os, psycopg2
c = psycopg2.connect(host='$H/pgdata', user='postgres', dbname='postgres'); c.autocommit = True
cur = c.cursor()
cur.execute(\"SELECT 1 FROM pg_roles WHERE rolname='advisory_ro'\")
sql = 'ALTER ROLE advisory_ro LOGIN PASSWORD %s' if cur.fetchone() else 'CREATE ROLE advisory_ro LOGIN PASSWORD %s'
cur.execute(sql, (os.environ['PGPW'],))
cur.execute('GRANT pg_read_all_data TO advisory_ro')
print('роль advisory_ro (только чтение) готова')
PY"

# ---------- ClickHouse: пользователь только для чтения с паролем ----------
CHHASH=$(printf '%s' "$CHPW" | sha256sum | cut -d' ' -f1)
cat > $H/users.xml <<EOF
<clickhouse>
  <profiles>
    <default><max_memory_usage>8000000000</max_memory_usage></default>
    <readonly_profile><readonly>1</readonly><max_memory_usage>4000000000</max_memory_usage></readonly_profile>
  </profiles>
  <quotas><default><interval><duration>3600</duration><queries>0</queries><errors>0</errors><result_rows>0</result_rows><read_rows>0</read_rows><execution_time>0</execution_time></interval></default></quotas>
  <users>
    <default>
      <password></password>
      <networks><ip>127.0.0.1</ip><ip>::1</ip></networks>
      <profile>default</profile><quota>default</quota>
      <access_management>1</access_management>
    </default>
    <advisory_ro>
      <password_sha256_hex>$CHHASH</password_sha256_hex>
      <networks>$(for n in $NETS; do printf "<ip>%s</ip>" "$n"; done)</networks>
      <profile>readonly_profile</profile><quota>default</quota>
      <grants><query>GRANT SELECT, SHOW ON *.*</query></grants>
    </advisory_ro>
  </users>
</clickhouse>
EOF
chown advisory:advisory $H/users.xml; chmod 600 $H/users.xml
sed -i "s#^ExecStart=.*#ExecStart=$H/bin/clickhouse server -- --path=$H/data/clickhouse --http_port=8123 --tcp_port=9000 --listen_host=0.0.0.0 --users_config=$H/users.xml#" /etc/systemd/system/advisory-clickhouse.service
systemctl daemon-reload
systemctl restart advisory-clickhouse
for i in $(seq 1 60); do curl -fs http://127.0.0.1:8123/ping >/dev/null 2>&1 && break; sleep 1; done

# ---------- Airflow: веб-интерфейс на 8080 с логином ----------
grep -q AIRFLOW__WEBSERVER__SECRET_KEY $H/secrets.env || printf 'AIRFLOW__WEBSERVER__SECRET_KEY=%s\n' "$(openssl rand -hex 24)" >> $H/secrets.env
sed -e 's#^Description=.*#Description=Airflow webserver (порт 8080, вход по логину)#' \
    -e '/^ExecStartPre=/d' \
    -e "s#^ExecStart=.*#ExecStart=$V/bin/airflow webserver --port 8080 --hostname $IP#" \
    $APP/deploy/ct/advisory-airflow.service > /etc/systemd/system/advisory-airflow-web.service
systemctl daemon-reload
su advisory -c "set -a; . $H/secrets.env; set +a; AIRFLOW_HOME=$H/airflow AIRFLOW__CORE__DAGS_FOLDER=$APP/dags AIRFLOW__CORE__LOAD_EXAMPLES=False $V/bin/airflow users delete -u admin >/dev/null 2>&1 || true"
su advisory -c "AIRFLOW_HOME=$H/airflow AIRFLOW__CORE__LOAD_EXAMPLES=False $V/bin/airflow users create -u admin -p '$AFPW' -f Admin -l Advisory -r Admin -e admin@localhost" >/dev/null 2>&1
systemctl enable --now advisory-airflow-web

# ---------- учётные данные ----------
{
  echo
  echo "== подключение из сетей $NETS (создано $(date +%F))"
  echo "PostgreSQL   host=$IP port=5432 user=advisory_ro password=$PGPW  (только чтение; базы: advisory, service)"
  echo "ClickHouse   http://$IP:8123  tcp $IP:9000  user=advisory_ro password=$CHPW  (только чтение; базы: analytics, service)"
  echo "Airflow      http://$IP:8080  user=admin password=$AFPW"
} >> $CRED
chmod 600 $CRED
systemctl --no-pager list-units 'advisory-*' | cat
ss -ltn | awk 'NR==1 || /:(80|5432|8123|9000|8080) /' | cat
