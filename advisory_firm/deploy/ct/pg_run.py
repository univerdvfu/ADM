"""Держит PostgreSQL 16 (pgserver) запущенным под systemd: остановка по SIGTERM корректно гасит сервер."""
import os
import signal
import sys

import pgserver

srv = pgserver.get_server(os.environ["PG_DATA"], cleanup_mode="stop")
print("PostgreSQL готов:", srv.get_uri(), flush=True)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
while True:
    signal.pause()
