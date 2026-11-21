"""Связка PostgreSQL (справочники, задания, карантин) + MinIO (сырьё) + ClickHouse."""
import io
import json
from datetime import timedelta, timezone
from pathlib import Path

from .contract import FORBIDDEN_FIELDS
from .loader import ingest_bars, ingest_trades
from .reference import load_reference

_ROOT = Path(__file__).resolve().parent.parent
PG_SCHEMAS = [_ROOT / "schema_pg.sql", _ROOT / "schema_advisory.sql"]
RAW_BUCKET = "raw-market"
MSK = timezone(timedelta(hours=3))


def create_pg_schema(conn):
    with conn.cursor() as cur:
        for f in PG_SCHEMAS:
            cur.execute(f.read_text(encoding="utf-8"))
    conn.commit()


def export_reference(pg, ch):
    """Отдельная задача выгрузки справочников: узкий белый список колонок.
    Брокеры, заказчики, счета и поручения не читаются вообще."""
    with pg.cursor() as cur:
        cur.execute("""SELECT session_id, session_date, start_time, end_time, venue, status
                       FROM trading_sessions""")
        sessions = [dict(zip(("session_id", "session_date", "start_at", "end_at",
                              "venue", "status"), r)) for r in cur.fetchall()]
        cur.execute("""SELECT si.session_id, si.ticker_id, i.instrument_id, t.ticker,
                              i.instrument_type, i.nominal_value, i.currency,
                              i.contract_term, i.exercise_style, i.maturity_date,
                              si.lot_size, si.tick_size, si.trading_status
                       FROM session_instruments si
                       JOIN tickers t USING (ticker_id)
                       JOIN instruments i USING (instrument_id)""")
        cols = ("session_id", "ticker_id", "instrument_id", "ticker", "instrument_type",
                "nominal_value", "currency", "contract_term", "exercise_style",
                "maturity_date", "lot_size", "tick_size", "trading_status")
        instruments = [dict(zip(cols, r)) for r in cur.fetchall()]
    for s in sessions:
        # время сделок Мосбиржи — местное московское (UTC+3, без перехода на летнее время)
        s["start_at"], s["end_at"] = (s[k].astimezone(MSK).replace(tzinfo=None) for k in ("start_at", "end_at"))
    return load_reference(ch, sessions, instruments)


def _redact(row):
    return {k: ("***" if k in FORBIDDEN_FIELDS else v) for k, v in row.items()}


def archive_raw(s3, batch_id, rows):
    body = "\n".join(json.dumps(_redact(r), default=str, ensure_ascii=False) for r in rows).encode()
    if not s3.bucket_exists(RAW_BUCKET):
        s3.make_bucket(RAW_BUCKET)
    key = f"{batch_id}.jsonl"
    s3.put_object(RAW_BUCKET, key, io.BytesIO(body), len(body), "application/x-ndjson")
    return key


def read_raw(s3, key):
    resp = s3.get_object(RAW_BUCKET, key)
    try:
        return [json.loads(l) for l in resp.read().decode().splitlines() if l]
    finally:
        resp.close(); resp.release_conn()


def run_batch(pg, ch, s3, batch_id, source_id, rows):
    """H3-H5: сырьё -> MinIO, проверка и загрузка -> ClickHouse, журнал и карантин -> PostgreSQL."""
    key = archive_raw(s3, batch_id, rows)
    out = ingest_trades(ch, batch_id, source_id, rows)
    if out["skipped_batch"]:
        return out
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO ingest_jobs (batch_id, source_id, raw_object, accepted,
                       duplicates, rejected) VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (batch_id) DO NOTHING""",
                    (batch_id, source_id, key, out["accepted"], out["duplicates"], out["rejected"]))
        for r in ch.rows("SELECT row_no, rule FROM ingest_rejects WHERE batch_id=%(b)s",
                         {"b": batch_id}):
            cur.execute("INSERT INTO quarantine VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (batch_id, r["row_no"], r["rule"]))
    pg.commit()
    return out


def run_bars_batch(pg, ch, batch_id, source_id, raw_object, bars):
    """Итоги дня: проверка до записи, бракованные бары в карантин PostgreSQL (только коды правил)."""
    out = ingest_bars(ch, batch_id, source_id, bars)
    if out["skipped_batch"]:
        return out
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO ingest_jobs (batch_id, source_id, raw_object, accepted,
                       duplicates, rejected) VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (batch_id) DO NOTHING""",
                    (batch_id, source_id, raw_object, out["accepted"], out["duplicates"], out["rejected"]))
        for r in ch.rows("SELECT row_no, rule FROM ingest_rejects WHERE batch_id=%(b)s", {"b": batch_id}):
            cur.execute("INSERT INTO quarantine VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (batch_id, r["row_no"], r["rule"]))
    pg.commit()
    return out
