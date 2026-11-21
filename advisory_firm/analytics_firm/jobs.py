"""Задачи для Airflow (и для тестов): загрузка у биржи -> MinIO -> PostgreSQL/ClickHouse ->
проверка качества -> черновики рекомендаций."""
import io
import json
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import psycopg2

from . import advisory, moex
from .stack import RAW_BUCKET, create_pg_schema

DEFAULT_TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "GMKN"]


def connect_pg():
    return psycopg2.connect(os.environ.get(
        "PG_DSN", f"host={os.path.expanduser('~/pgdata')} dbname=advisory user=postgres"))


def connect_ch(database=None):
    from .db import Db
    database = database or os.getenv("CH_DATABASE", "analytics")
    return Db(host=os.getenv("CH_HOST", "localhost"), port=int(os.getenv("CH_PORT", "8123")),
              database=database)


def connect_s3():
    from minio import Minio
    return Minio(os.getenv("MINIO_ENDPOINT", "127.0.0.1:39010"),
                 os.getenv("MINIO_USER", "testadmin"), os.getenv("MINIO_PASSWORD", "testpass123"),
                 secure=False)


def ensure_schemas(pg, ch):
    with pg.cursor() as cur:
        cur.execute("SELECT to_regclass('public.issuers')")
        exists = cur.fetchone()[0] is not None
    if not exists:
        create_pg_schema(pg)
    ch.create_schema()
    return {"pg_created": not exists}


def fetch_raw(s3, tickers, day, fetch=None, days_back=90):
    """Скачивает историю и карточки бумаг у API Мосбиржи, кладёт сырьё в MinIO."""
    fetch = fetch or moex_fetch
    if not s3.bucket_exists(RAW_BUCKET):
        s3.make_bucket(RAW_BUCKET)
    keys = []
    for secid in tickers:
        hist, sec = fetch(secid, day - timedelta(days=days_back), day)
        for kind, payload in (("hist", hist), ("sec", sec)):
            body = json.dumps(payload, ensure_ascii=False).encode()
            key = f"moex/{day}/{kind}_{secid}.json"
            s3.put_object(RAW_BUCKET, key, io.BytesIO(body), len(body), "application/json")
            keys.append(key)
    return keys


def moex_fetch(secid, start, end):
    hist = moex._get(f"https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/"
                     f"TQBR/securities/{secid}.json?from={start}&till={end}&iss.only=history")
    sec = moex.fetch_security(secid)
    return hist, sec


def load_from_raw(pg, ch, s3, tickers, day, workdir, report=None):
    """Читает сырьё из MinIO и загружает справочники/бары."""
    wd = Path(workdir)
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    for secid in tickers:
        for kind in ("hist", "sec"):
            s3.fget_object(RAW_BUCKET, f"moex/{day}/{kind}_{secid}.json", str(wd / f"{kind}_{secid}.json"))
    return advisory.seed_from_moex(pg, ch, wd, tickers, report)


def quality_check(ch):
    r = ch.rows("""SELECT count() total,
                          countIf(high < low OR close > high OR close < low OR open <= 0) bad,
                          uniqExact(ticker_id) tickers, max(trade_date) last_date
                   FROM daily_bars FINAL""")[0]
    if r["total"] == 0 or r["bad"] > 0:
        raise ValueError(f"quality check failed: {r}")
    return {k: str(v) for k, v in r.items()}


def refresh_recommendations(pg, ch, author="airflow-bot"):
    """Черновики по всем клиентам и бумагам; повтор на тех же данных не плодит дубли."""
    with pg.cursor() as cur:
        cur.execute("SELECT client_id FROM advisory_clients WHERE status='active'")
        clients = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ticker_id FROM tickers")
        tickers = [r[0] for r in cur.fetchall()]
    made = 0
    for c in clients:
        for t in tickers:
            m = advisory.metrics(ch, pg, t)
            if m is None:
                continue
            with pg.cursor() as cur:
                cur.execute("SELECT 1 FROM recommendations WHERE client_id=%s AND ticker_id=%s "
                            "AND data_cutoff=%s AND method_version=%s",
                            (c, t, m["cutoff"], advisory.METHOD_VERSION))
                if cur.fetchone():
                    continue
            advisory.advise(pg, ch, c, t, author)
            made += 1
    return made
