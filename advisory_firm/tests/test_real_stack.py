"""PostgreSQL (внешний реляционный контур) + MinIO (сырьё) + ClickHouse (аналитика)."""
from decimal import Decimal

import psycopg2
import pytest

from analytics_firm import analytics, stack
from analytics_firm.contract import FORBIDDEN_FIELDS
from conftest import SBER, SESSION, trade


def sql(pg, q, args=None):
    with pg.cursor() as cur:
        cur.execute(q, args)
        return cur.fetchall() if cur.description else None


def fails(pg, q, args=None):
    with pytest.raises(psycopg2.Error):
        sql(pg, q, args)
    pg.rollback()


@pytest.fixture
def seeded(pg):
    sql(pg, "INSERT INTO issuers VALUES (1,'Sber','RU')")
    sql(pg, """INSERT INTO instruments VALUES
        (1,1,'stock',20.8,'RUB',NULL,NULL,NULL),
        (2,1,'future',1,'USDT','perpetual',NULL,NULL)""")
    sql(pg, "INSERT INTO tickers VALUES (1,1,'SBER'),(2,2,'SBERP')")
    sql(pg, """INSERT INTO trading_sessions VALUES
        (%s,'2026-10-29','2026-10-29 10:00+03','2026-10-29 18:50+03','MOEX/TQBR','open')""",
        (SESSION,))
    sql(pg, "INSERT INTO session_instruments VALUES (%s,1,'open',1,0.01),(%s,2,'open',1,0.01)",
        (SESSION, SESSION))
    sql(pg, "INSERT INTO brokers VALUES (1,'Broker A','active')")
    sql(pg, "INSERT INTO customers VALUES (1,1,'client-1')")
    pg.commit()
    return pg


def test_pg_nominal_keeps_20_8_and_currency_is_4_wide(seeded):
    sql(seeded, "UPDATE instruments SET nominal_value=20.12345678 WHERE instrument_id=1")
    row = sql(seeded, "SELECT nominal_value, currency FROM instruments WHERE instrument_id=1")[0]
    assert row[0] == Decimal("20.12345678") and row[1] == "RUB "
    fails(seeded, "UPDATE instruments SET currency='RUBLE' WHERE instrument_id=1")


def test_pg_future_and_option_attribute_rules(seeded):
    ins = "INSERT INTO instruments VALUES (%s,1,%s,1,'USD',%s,%s,%s)"
    fails(seeded, ins, (10, "future", "fixed", None, None))            # нет даты погашения
    fails(seeded, ins, (11, "future", "perpetual", None, "2027-01-01"))  # у бессрочного нет даты
    fails(seeded, ins, (12, "option", None, None, None))               # нет стиля
    fails(seeded, ins, (13, "stock", "fixed", None, "2027-01-01"))     # акция без производных признаков
    sql(seeded, ins, (14, "option", None, "european", None))
    sql(seeded, ins, (15, "future", "fixed", None, "2027-03-01"))


def test_pg_ticker_is_object_and_unique(seeded):
    fails(seeded, "INSERT INTO tickers VALUES (9,1,'SBER')")
    fails(seeded, "INSERT INTO tickers VALUES (9,999,'XXX')")


def test_pg_instrument_availability_depends_on_session(seeded):
    fails(seeded, "INSERT INTO session_instruments VALUES (777,1,'open',1,0.01)")
    sql(seeded, "INSERT INTO owner_accounts VALUES (1,1,1,1)")
    sql(seeded, "INSERT INTO trading_sessions VALUES (5,'2026-10-30','2026-10-30 10:00+03',"
                "'2026-10-30 18:00+03','MOEX/TQBR','open')")
    seeded.commit()
    fails(seeded, "INSERT INTO client_requests VALUES (1,1,1,5,'buy',10,NULL)")  # тикер не допущен к сессии 5
    sql(seeded, "INSERT INTO client_requests VALUES (1,1,1,%s,'buy',10,100.5)", (SESSION,))


def test_pg_owner_account_is_mandatory_and_goes_through_broker(seeded):
    sql(seeded, "INSERT INTO brokers VALUES (2,'Broker B','active')")
    fails(seeded, "INSERT INTO customers VALUES (5,999,'x')")               # заказчик без брокера
    fails(seeded, "INSERT INTO owner_accounts VALUES (1,1,2,1)")            # чужой брокер заказчика
    fails(seeded, "INSERT INTO owner_accounts VALUES (1,1,1,NULL)")         # ticker_id обязателен
    fails(seeded, "INSERT INTO client_requests VALUES (1,404,1,%s,'buy',1,NULL)", (SESSION,))
    sql(seeded, "INSERT INTO owner_accounts VALUES (1,1,1,1)")


def test_export_gives_clickhouse_reference_without_participants(seeded, db):
    out = stack.export_reference(seeded, db)
    assert out["instruments"] == 2 and not out["rejected"]
    cur = db.rows("SELECT ticker, nominal_value, currency, contract_term FROM "
                  "ref_session_instruments ORDER BY ticker_id")
    assert cur[0]["nominal_value"] == Decimal("20.8")
    assert cur[1]["contract_term"] == "perpetual"
    for table, cols in db.tables().items():
        assert not set(cols) & FORBIDDEN_FIELDS, table
    assert not {"brokers", "customers", "owner_accounts", "client_requests"} & set(db.tables())


def test_minio_roundtrip_redacts_participant_ids(s3):
    key = stack.archive_raw(s3, "raw1", [dict(trade(1, "100"), user_id=777)])
    back = stack.read_raw(s3, key)
    assert back[0]["user_id"] == "***" and "777" not in str(back)


def test_end_to_end_pg_minio_clickhouse(seeded, db, s3):
    stack.export_reference(seeded, db)
    rows = [trade(i, 100 + i, second=i) for i in range(1, 7)] + [
        dict(trade(50, "100"), account_id=3), trade(51, "100", ticker_id=99)]
    out = stack.run_batch(seeded, db, s3, "e2e-1", "MOEX-ISS", rows)
    assert (out["accepted"], out["rejected"]) == (6, 2)
    job = sql(seeded, "SELECT raw_object, accepted, rejected FROM ingest_jobs")[0]
    assert job == ("e2e-1.jsonl", 6, 2)
    q = sorted(r[0] for r in sql(seeded, "SELECT rule FROM quarantine"))
    assert q == ["forbidden_field", "ticker_not_admitted_to_session"]
    assert len(stack.read_raw(s3, job[0])) == 8
    analytics.build_ohlcv(db)
    analytics.compute_signals(db)
    assert analytics.get_signal(db, SBER, SESSION)["signal"] == "up"


def test_rerun_batch_is_idempotent_across_all_three_stores(seeded, db, s3):
    stack.export_reference(seeded, db)
    rows = [trade(i, 100) for i in range(1, 4)]
    stack.run_batch(seeded, db, s3, "rr", "MOEX-ISS", rows)
    again = stack.run_batch(seeded, db, s3, "rr", "MOEX-ISS", rows)
    assert again["skipped_batch"]
    assert db.rows("SELECT count() n FROM market_trades")[0]["n"] == 3
    assert sql(seeded, "SELECT count(*) FROM ingest_jobs")[0][0] == 1
    assert len(list(s3.list_objects(stack.RAW_BUCKET))) == 1
