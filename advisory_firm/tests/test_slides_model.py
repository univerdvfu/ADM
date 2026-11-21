"""15 тестов: БД из «Биржа (2).pptx» (слайды 6-7) против нашей модели аналитической зоны.
Тесты slide_* создают таблицы ровно как на слайде и показывают слабое место;
остальные проверяют исправленную модель."""
import hashlib
from decimal import Decimal

import pytest

from analytics_firm import analytics, anonymize, moex, recommendations as rec
from analytics_firm.contract import FORBIDDEN_FIELDS, Reject
from analytics_firm.loader import ingest_trades
from analytics_firm.reference import load_reference, validate_instrument
from conftest import (SBER, SESSION, instrument, moex_security_payload,
                      moex_trades_payload, session, trade)

SLIDE_TRADES = """CREATE TABLE slide_fact_trades (
    trade_id UInt64, buy_order_id UInt64, sell_order_id UInt64, instrument_id UInt64,
    buy_broker_id UInt64, sell_broker_id UInt64, session_id UInt64,
    price Decimal(20,8), quantity UInt64, trade_time DateTime64(6), trade_status String
) ENGINE = MergeTree ORDER BY (instrument_id, trade_time)"""
SLIDE_ORDER_EVENTS_COLS = {"event_id", "order_id", "broker_id", "instrument_id"}


def _series(db, prices, ticker_id=SBER, start=1, second0=0):
    rows = [trade(start + i, p, ticker_id=ticker_id, second=second0 + i)
            for i, p in enumerate(prices)]
    return ingest_trades(db, f"b{ticker_id}-{start}", "MOEX-ISS", rows)


# 1-2. типы на слайде 6 / 7 --------------------------------------------------

def test_01_slide_nominal_20_4_loses_precision_ours_20_8_keeps(ref_db):
    ref_db.command("CREATE TABLE slide_dim (nominal Decimal(20,4)) ENGINE=Memory")
    ref_db.command("INSERT INTO slide_dim VALUES (20.12345678)")
    assert ref_db.rows("SELECT nominal FROM slide_dim")[0]["nominal"] == Decimal("20.1234")
    load_reference(ref_db, [], [instrument(7, "TST", nominal_value="20.12345678")])
    got = ref_db.rows("SELECT nominal_value FROM ref_session_instruments WHERE ticker_id=7")
    assert got[0]["nominal_value"] == Decimal("20.12345678")


def test_02_slide_currency_3_cannot_hold_4_ours_fixed_4(ref_db):
    ref_db.command("CREATE TABLE slide_cur (c FixedString(3)) ENGINE=Memory")
    with pytest.raises(Exception):
        ref_db.command("INSERT INTO slide_cur VALUES ('USDT')")
    load_reference(ref_db, [], [instrument(8, "TT", currency="USDT")])
    cur = ref_db.rows("SELECT currency FROM ref_session_instruments WHERE ticker_id=8")[0]
    cur = cur["currency"].decode() if isinstance(cur["currency"], bytes) else cur["currency"]
    assert cur == "USDT"


# 3. ключ свечи ---------------------------------------------------------------

def test_03_slide_candle_key_without_session_merges_sessions(ref_db):
    load_reference(ref_db, [dict(session("2026-10-29"), session_id=SESSION + 1)],
                   [instrument(SBER, "SBER", session_id=SESSION + 1)])
    ingest_trades(ref_db, "a", "MOEX-ISS", [trade(1, "100"), trade(2, "101", second=5)])
    ingest_trades(ref_db, "b", "MOEX-ISS", [trade(3, "200", session_id=SESSION + 1)])
    analytics.build_ohlcv(ref_db)
    ours = ref_db.rows("SELECT session_id FROM agg_ohlcv_1m FINAL")
    assert len(ours) == 2                                    # у нас свечи раздельны
    slide_key = ref_db.rows("""SELECT count() n FROM (SELECT 1 FROM market_trades
        GROUP BY ticker_id, toStartOfMinute(event_time))""")[0]["n"]
    assert slide_key == 1                                    # ключ со слайда смешал бы сессии


# 4. повторы из Kafka ----------------------------------------------------------

def test_04_slide_trades_have_no_dedupe_key_ours_idempotent(ref_db):
    ref_db.command(SLIDE_TRADES)
    row = "(1,10,11,1,5,6,1,100,10,'2026-10-29 10:00:00.000000','done')"
    ref_db.command(f"INSERT INTO slide_fact_trades VALUES {row}")
    ref_db.command(f"INSERT INTO slide_fact_trades VALUES {row}")      # повтор доставки
    assert ref_db.rows("SELECT sum(quantity) q FROM slide_fact_trades")[0]["q"] == 20
    batch = [trade(1, "100")]
    ingest_trades(ref_db, "k1", "MOEX-ISS", batch)
    ingest_trades(ref_db, "k2", "MOEX-ISS", batch)                     # то же событие, другой пакет
    assert ref_db.rows("SELECT sum(quantity) q FROM market_trades")[0]["q"] == 10


# 5-6. ID участников и ссылка на тикер -------------------------------------------

def test_05_slide_analytics_carries_broker_and_order_ids_ours_does_not(ref_db):
    ref_db.command(SLIDE_TRADES)
    slide_cols = {c for t, cols in ref_db.tables().items() if t.startswith("slide_")
                  for c in cols}
    assert {"buy_broker_id", "sell_broker_id", "buy_order_id"} <= slide_cols
    for table, cols in ref_db.tables().items():
        if not table.startswith("slide_"):
            assert not set(cols) & (FORBIDDEN_FIELDS | {"order_id", "buy_order_id"}), table


def test_06_ticker_is_reference_by_ticker_id_not_string(ref_db):
    cols = ref_db.tables()["market_trades"]
    assert "ticker_id" in cols and "ticker" not in cols
    ingest_trades(ref_db, "x", "MOEX-ISS", [trade(1, "100")])
    joined = ref_db.rows("""SELECT i.ticker FROM market_trades t
        JOIN (SELECT * FROM ref_session_instruments FINAL) i
          ON t.ticker_id=i.ticker_id AND t.session_id=i.session_id""")
    assert joined[0]["ticker"] == "SBER"


# 7-8. инструмент зависит от сессии, деривативы ----------------------------------

def test_07_instrument_depends_on_session(ref_db):
    load_reference(ref_db, [dict(session("2026-10-30"), session_id=20261030)], [])
    out = ingest_trades(ref_db, "s", "MOEX-ISS", [trade(1, "10", session_id=20261030)])
    assert out["reject_rules"] == ["ticker_not_admitted_to_session"]


@pytest.mark.parametrize("raw,rule", [
    (dict(instrument_type="future", contract_term="fixed"), "maturity_required"),
    (dict(instrument_type="future", contract_term="perpetual", maturity_date="2027-01-01"),
     "maturity_forbidden"),
    (dict(instrument_type="option", exercise_style="bermudan"), "bad_option_attrs"),
])
def test_08_future_term_and_option_style_rules(raw, rule):
    with pytest.raises(Reject) as e:
        validate_instrument(instrument(9, "D", **raw))
    assert e.value.rule == rule
    ok = validate_instrument(instrument(9, "D", instrument_type="option",
                                        exercise_style="american"))
    assert ok["exercise_style"] == "american"


# 9-10. обезличивание отдельной задачей ------------------------------------------

def test_09_pseudonym_is_keyed_stable_and_not_plain_hash():
    a1 = anonymize.pseudonym(b"k1", 4242)
    assert a1 == anonymize.pseudonym(b"k1", 4242)
    assert a1 != anonymize.pseudonym(b"k2", 4242)
    assert a1 != hashlib.sha256(b"4242").hexdigest()[:16]


def test_10_export_task_strips_ids_and_returns_no_mapping():
    src = [dict(trade(1, "100"), user_id=5, account_id=9, participant_id=77, note="x")]
    out = anonymize.export_market_slice(src, b"secret", keep_alias=True)
    assert not set(out[0]) & FORBIDDEN_FIELDS and "note" not in out[0]
    assert out[0]["participant_alias"] != "77" and "77" not in str(out)
    assert "participant_alias" not in anonymize.export_market_slice(src, b"s")[0]


# 11-12. рекомендации и заказчик ------------------------------------------------------

@pytest.fixture
def recommended(ref_db):
    _series(ref_db, ["100", "101", "102", "103", "104"])
    analytics.build_ohlcv(ref_db)
    analytics.compute_signals(ref_db)
    return ref_db, rec.draft(ref_db, "anna", SBER, SESSION)


def test_11_publish_requires_independent_approval(recommended):
    db, rid = recommended
    with pytest.raises(ValueError):
        rec.publish(db, "boris", rid)
    with pytest.raises(rec.Denied):
        rec.review(db, "anna", rid, True)
    rec.review(db, "boris", rid, True)
    rec.publish(db, "boris", rid)


def test_12_customer_gets_only_published_without_ids(recommended):
    db, rid = recommended
    assert rec.customer_report(db) == []
    rec.review(db, "boris", rid, True)
    rec.publish(db, "boris", rid)
    row = rec.customer_report(db)[0]
    assert set(row) == {"rec_id", "ticker", "action", "horizon", "rationale",
                        "method_version", "published_at"}


# 13-15. карантин, порядок событий, данные API ------------------------------------------

def test_13_quarantine_log_keeps_rule_codes_not_row_copies(ref_db):
    ingest_trades(ref_db, "q", "MOEX-ISS", [trade(1, "100", user_id=123456)])
    rows = ref_db.rows("SELECT * FROM ingest_rejects")
    assert rows[0]["rule"] == "forbidden_field" and "123456" not in str(rows)


def test_14_open_close_follow_event_time_not_arrival(ref_db):
    ingest_trades(ref_db, "o", "MOEX-ISS", [trade(3, "110", second=30),
                                            trade(1, "100", second=1),
                                            trade(2, "105", second=10)])
    analytics.build_ohlcv(ref_db)
    c = ref_db.rows("SELECT open, close FROM agg_ohlcv_1m FINAL")[0]
    assert (c["open"], c["close"]) == (Decimal(100), Decimal(110))


def test_15_moex_api_payload_goes_through_whole_pipeline(db):
    day = "2026-10-29"
    inst = moex.parse_instrument(moex_security_payload(), SBER, 1, day)
    load_reference(db, [moex.parse_session(day)], [inst])
    series = [(500 + i, f"10:00:{i:02d}", 298.0 + i * 0.5, 10) for i in range(8)]
    rows = moex.parse_trades(moex_trades_payload(series), SBER)
    assert "BUYSELL" not in rows[0]
    assert ingest_trades(db, "m1", moex.SOURCE_ID, rows)["accepted"] == 8
    analytics.build_ohlcv(db)
    analytics.compute_signals(db)
    assert analytics.get_signal(db, SBER, moex.session_id_for(day))["signal"] == "up"
