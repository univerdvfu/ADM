#!/usr/bin/env bash
# Общие переменные. Подключается другими скриптами: source deploy/env.sh
export PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export HOME_DIR="${HOME}/advisory-stack"           # бинарники и данные сервисов
export VENV="${HOME_DIR}/venv"

export CH_HOST=127.0.0.1 CH_PORT=8123
export MINIO_ENDPOINT=127.0.0.1:39010 MINIO_USER=testadmin MINIO_PASSWORD=testpass123
export PG_DATA="${HOME_DIR}/pgdata"
export PG_DSN="host=${PG_DATA} dbname=advisory user=postgres"

export AIRFLOW_HOME="${HOME_DIR}/airflow"
export AIRFLOW__CORE__DAGS_FOLDER="${PROJECT}/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export PYTHONPATH="${PROJECT}"

# Секреты (если есть): создаются deploy/ct/install_ct.sh; в локальной разработке остаются значения по умолчанию
[ -f "$HOME_DIR/secrets.env" ] && { set -a; . "$HOME_DIR/secrets.env"; set +a; }
# расписание DAG считается по московскому времени (19:00 MSK после закрытия торгов)
export AIRFLOW__CORE__DEFAULT_TIMEZONE=Europe/Moscow
