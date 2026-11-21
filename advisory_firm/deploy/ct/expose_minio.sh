#!/usr/bin/env bash
# Открывает MinIO (S3 API :9100 и консоль :9101) в сети контейнера; для входа создаётся пользователь только для чтения.
# Запускать от root внутри контейнера:  bash expose_minio.sh <IP контейнера>   (нужен бинарник mc в /tmp/mc)
set -euo pipefail
IP="${1:?укажите IP контейнера}"
H=/home/advisory/advisory-stack
CRED=/root/advisory-credentials.txt
set -a; . $H/secrets.env; set +a
ROPW=$(openssl rand -hex 10)

[ -f /tmp/mc ] && install -o advisory -g advisory -m 755 /tmp/mc $H/bin/mc
UNIT=/etc/systemd/system/advisory-minio.service
sed -i "s#^ExecStart=.*#ExecStart=$H/bin/minio server $H/data/minio --address 0.0.0.0:9100 --console-address 0.0.0.0:9101#" $UNIT
grep -q MINIO_BROWSER_REDIRECT_URL $UNIT || sed -i "s#^User=advisory#User=advisory\nEnvironment=MINIO_BROWSER_REDIRECT_URL=http://$IP:9101#" $UNIT
for u in advisory-service advisory-airflow advisory-airflow-web; do
  sed -i 's#MINIO_ENDPOINT=127.0.0.1:39010#MINIO_ENDPOINT=127.0.0.1:9100#' /etc/systemd/system/$u.service
done
systemctl daemon-reload
systemctl restart advisory-minio
for i in $(seq 1 30); do curl -fs http://127.0.0.1:9100/minio/health/live >/dev/null 2>&1 && break; sleep 1; done

export MC_CONFIG_DIR=/tmp/mcconf
$H/bin/mc alias set local http://127.0.0.1:9100 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
$H/bin/mc admin user rm local advisory_ro >/dev/null 2>&1 || true
$H/bin/mc admin user add local advisory_ro "$ROPW" >/dev/null
# встроенная политика readonly не разрешает ListBucket, поэтому своя: просмотр списков и чтение объектов
cat > /tmp/ro-policy.json <<'JSON'
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:ListAllMyBuckets","s3:GetBucketLocation","s3:ListBucket"],"Resource":["arn:aws:s3:::*"]},
 {"Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::*"]}]}
JSON
$H/bin/mc admin policy create local advisory-ro-list /tmp/ro-policy.json >/dev/null
rm -f /tmp/ro-policy.json
$H/bin/mc admin policy attach local advisory-ro-list --user advisory_ro >/dev/null
rm -rf /tmp/mcconf

systemctl restart advisory-service advisory-airflow advisory-airflow-web
{
  echo "MinIO        S3 API http://$IP:9100   консоль http://$IP:9101   user=advisory_ro password=$ROPW  (только чтение)"
  echo "MinIO admin  user=$MINIO_ROOT_USER  password в $H/secrets.env (MINIO_ROOT_PASSWORD), только внутри контейнера"
} >> $CRED
chmod 600 $CRED
ss -ltn | grep -E ':(9100|9101) '
