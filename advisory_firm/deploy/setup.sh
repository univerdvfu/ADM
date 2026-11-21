#!/usr/bin/env bash
# Установка стека в Linux / Ubuntu WSL без sudo. Скачивает около 1 ГБ.
#   bash deploy/setup.sh
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p "$HOME_DIR/bin" "$AIRFLOW_HOME"
cd "$HOME_DIR"

echo "== ClickHouse (бинарник с clickhouse.com)"
if [ ! -x bin/clickhouse ]; then
  (cd bin && curl -fsSL https://clickhouse.com/ | sh)
fi

echo "== MinIO"
# Готовых сборок на dl.min.io больше нет (ответ 410), поэтому собираем из исходников.
if [ ! -x bin/minio ]; then
  if command -v go >/dev/null; then
    GOBIN="$HOME_DIR/bin" go install github.com/minio/minio@latest
  else
    echo "Нужен Go (https://go.dev/dl/) либо положите готовый бинарник minio в $HOME_DIR/bin/"
    echo "Кросс-сборка на Windows:  GOOS=linux GOARCH=amd64 go install github.com/minio/minio@latest"
    exit 1
  fi
fi

echo "== Python-окружение, PostgreSQL (pgserver), Airflow"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv --without-pip "$VENV"          # python3-venv без ensurepip: pip ставим сами
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o get-pip.py
  "$VENV/bin/python" get-pip.py -q
fi
PYV=$("$VENV/bin/python" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
AF=2.10.5
"$VENV/bin/pip" install -q "apache-airflow==$AF" -r "$PROJECT/requirements.txt" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-$AF/constraints-$PYV.txt"
echo "Готово. Дальше: bash deploy/start.sh"
