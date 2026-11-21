import json
import os
import socket
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from analytics_firm.db import Db

FIX = Path(__file__).parent / "fixtures"

# ---------- трассировка для сервиса просмотра (TEST_TRACE=путь к jsonl) ----------
import json
import time

TRACE = os.getenv("TEST_TRACE")


def _emit(ev):
    with open(TRACE, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")


def _current():
    cur = os.environ.get("PYTEST_CURRENT_TEST", "")
    return cur.rsplit("::", 1)[-1].split(" ")[0] if cur.endswith("(call)") else None


def _trace(kind, sql, started, rows=None):
    name = _current()
    if name:
        _emit({"t": "sql", "test": name, "db": kind, "sql": " ".join(str(sql).split())[:300],
               "ms": round((time.time() - started) * 1000, 1), "rows": rows})


if TRACE:
    import psycopg2.extensions
    from analytics_firm.db import Db as _Db

    def _wrap(method):
        orig = getattr(_Db, method)

        def inner(self, *a, **k):
            t0 = time.time()
            r = orig(self, *a, **k)
            if method == "insert":
                _trace("ClickHouse", f"INSERT INTO {a[0]} ({len(a[2]) if len(a) > 2 else 0} строк)", t0)
            else:
                _trace("ClickHouse", a[0], t0, len(r) if isinstance(r, list) else None)
            return r
        setattr(_Db, method, inner)
    for _m in ("rows", "command", "insert"):
        _wrap(_m)

    class TraceCursor(psycopg2.extensions.cursor):
        def execute(self, query, vars=None):
            t0 = time.time()
            try:
                return super().execute(query, vars)
            finally:
                _trace("PostgreSQL", query if isinstance(query, str) else query.decode(), t0, self.rowcount)


def pytest_runtest_logstart(nodeid, location):
    if TRACE:
        _emit({"t": "start", "test": nodeid.rsplit("::", 1)[-1], "ts": time.time()})


def pytest_runtest_logreport(report):
    if TRACE and (report.when == "call" or (report.when != "call" and report.outcome == "failed")):
        _emit({"t": "end", "test": report.nodeid.rsplit("::", 1)[-1],
               "outcome": report.outcome if report.when == "call" else "error",
               "duration": round(report.duration, 3),
               "error": str(report.longrepr)[-1800:] if report.outcome == "failed" else ""})

SESSION = 20261029
SBER, GAZP = 1, 2


@pytest.fixture
def db():
    """Чистая база ClickHouse на каждый тест (CH_HOST/CH_PORT, по умолчанию localhost:8123)."""
    name = "t_" + uuid.uuid4().hex[:10]
    host, port = os.getenv("CH_HOST", "localhost"), int(os.getenv("CH_PORT", "8123"))
    try:
        socket.create_connection((host, port), timeout=2).close()
    except OSError as e:
        pytest.skip(f"ClickHouse недоступен на {host}:{port}: {e}")
    try:
        d = Db(host=os.getenv("CH_HOST", "localhost"),
               port=int(os.getenv("CH_PORT", "8123")), database=name)
    except Exception as e:
        pytest.skip(f"ClickHouse недоступен: {e}")
    d.create_schema()
    yield d
    d.drop()


def instrument(ticker_id, ticker, **kw):
    base = {"session_id": SESSION, "ticker_id": ticker_id, "instrument_id": ticker_id,
            "ticker": ticker, "instrument_type": "stock", "nominal_value": "20.8",
            "currency": "RUB", "lot_size": 1, "tick_size": "0.01"}
    base.update(kw)
    return base


def session(day="2026-10-29"):
    return {"session_id": SESSION, "session_date": day, "start_at": f"{day}T10:00:00",
            "end_at": f"{day}T18:50:00", "venue": "MOEX/TQBR"}


def trade(n, price, ticker_id=SBER, minute=0, second=0, qty=10, **kw):
    t = datetime(2026, 10, 29, 10, minute, second)
    row = {"source_id": "MOEX-ISS", "event_id": str(n), "ticker_id": ticker_id,
           "session_id": SESSION, "event_time": t, "price": price, "quantity": qty}
    row.update(kw)
    return row


@pytest.fixture
def ref_db(db):
    from analytics_firm.reference import load_reference
    load_reference(db, [session()], [instrument(SBER, "SBER"), instrument(GAZP, "GAZP")])
    return db


def moex_security_payload():
    return json.loads((FIX / "moex_security_SBER.json").read_text(encoding="utf-8"))


def moex_trades_payload(rows):
    cols = ["TRADENO", "TRADETIME", "SECID", "PRICE", "QUANTITY", "PERIOD", "VALUE",
            "BOARDID", "SYSTIME", "BUYSELL", "DECIMALS", "TRADINGSESSION", "TRADEDATE"]
    data = [[n, tm, "SBER", p, q, "N", p * q, "TQBR", f"2026-10-29 {tm}", "B", 2, "1",
             "2026-10-29"] for n, tm, p, q in rows]
    return {"trades": {"columns": cols, "data": data}}


# ---------- PostgreSQL (pgserver) и MinIO ----------

MINIO = (os.getenv("MINIO_ENDPOINT", "127.0.0.1:39000"),
         os.getenv("MINIO_USER", "testadmin"), os.getenv("MINIO_PASSWORD", "testpass123"))


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory):
    try:
        import pgserver
        srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    except Exception as e:
        pytest.skip(f"PostgreSQL недоступен: {e}")
    yield srv
    srv.cleanup()


@pytest.fixture
def pg(pg_server):
    import psycopg2
    from analytics_firm.stack import create_pg_schema
    name = "t_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(pg_server.get_uri())
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    conn = psycopg2.connect(pg_server.get_uri(database=name),
                            cursor_factory=TraceCursor if TRACE else None)
    create_pg_schema(conn)
    yield conn
    conn.close()
    admin.cursor().execute(f"DROP DATABASE {name} WITH (FORCE)")
    admin.close()


@pytest.fixture
def s3():
    from minio import Minio
    try:
        socket.create_connection((MINIO[0].split(":")[0], int(MINIO[0].split(":")[1])), 2).close()
    except OSError as e:
        pytest.skip(f"MinIO недоступен: {e}")
    client = Minio(MINIO[0], MINIO[1], MINIO[2], secure=False)
    yield client
    from analytics_firm.stack import RAW_BUCKET
    if client.bucket_exists(RAW_BUCKET):
        for o in client.list_objects(RAW_BUCKET, recursive=True):
            client.remove_object(RAW_BUCKET, o.object_name)
        client.remove_bucket(RAW_BUCKET)
