"""Тесты на реальном ClickHouse: схема, загрузка, свечи, сигналы, рекомендации, роли."""
from decimal import Decimal

import pytest

from analytics_firm import analytics, moex, recommendations as rec
from analytics_firm.contract import FORBIDDEN_FIELDS
from analytics_firm.loader import ingest_trades
from analytics_firm.reference import load_reference
from conftest import (GAZP, SBER, SESSION, instrument, moex_security_payload,
                      moex_trades_payload, session, trade)


# ---------- схема и уровни защиты ----------

def test_schema_has_no_participant_columns_or_tables(db):
    tables = db.tables()
    for name, cols in tables.items():
        assert not set(cols) & FORBIDDEN_FIELDS, name
    assert not {"customers", "owner_accounts", "brokers", "client_requests",
                "dim_brokers"} & set(tables)


def test_column_types_match_slides(db):
    types = {(r["table"], r["name"]): r["type"] for r in db.rows(
        "SELECT table, name, type FROM system.columns WHERE database=%(d)s",
        {"d": db.database})}
    assert types[("ref_session_instruments", "nominal_value")] == "Decimal(20, 8)"
    assert types[("ref_session_instruments", "currency")] == "FixedString(4)"
    assert types[("market_trades", "price")] == "Decimal(20, 8)"
    assert types[("agg_ohlcv_1m", "turnover")] == "Decimal(30, 8)"


def test_reference_roundtrip_nominal_and_currency(ref_db):
    r = ref_db.rows("SELECT nominal_value, currency FROM ref_session_instruments "
                    "WHERE ticker_id=1")[0]
    assert r["nominal_value"] == Decimal("20.8")
    cur = r["currency"].decode() if isinstance(r["currency"], bytes) else r["currency"]
    assert cur == "RUB "  # ширина ровно 4 знака


def test_instrument_for_unknown_session_rejected(db):
    out = load_reference(db, [session()], [instrument(1, "SBER", session_id=999)])
    assert out["instruments"] == 0 and out["rejected"] == [(0, "unknown_session")]


# ---------- загрузка ----------

def test_ingest_accepts_valid_and_logs_rule_codes_only(ref_db):
    rows = [trade(1, "300.1"), trade(2, "300.2", user_id=5),
            trade(3, "-1"), trade(4, "300.3", ticker_id=99)]
    out = ingest_trades(ref_db, "b1", "MOEX-ISS", rows)
    assert (out["accepted"], out["rejected"]) == (1, 3)
    assert sorted(out["reject_rules"]) == ["bad_price", "forbidden_field",
                                           "ticker_not_admitted_to_session"]
    logged = ref_db.rows("SELECT * FROM ingest_rejects")
    assert set(logged[0]) == {"batch_id", "row_no", "rule", "logged_at"}


def test_ticker_must_be_admitted_to_that_session(ref_db):
    load_reference(ref_db, [dict(session("2026-10-30"), session_id=20261030)], [])
    row = trade(1, "10", session_id=20261030)
    out = ingest_trades(ref_db, "b1", "MOEX-ISS", [row])
    assert out["reject_rules"] == ["ticker_not_admitted_to_session"]


def test_foreign_source_rejected(ref_db):
    out = ingest_trades(ref_db, "b1", "MOEX-ISS", [trade(1, "10", source_id="OTHER")])
    assert out["reject_rules"] == ["foreign_source"]


def test_same_batch_is_idempotent(ref_db):
    rows = [trade(i, "300") for i in range(1, 4)]
    ingest_trades(ref_db, "b1", "MOEX-ISS", rows)
    again = ingest_trades(ref_db, "b1", "MOEX-ISS", rows)
    assert again["skipped_batch"] is True
    assert ref_db.rows("SELECT count() n FROM market_trades")[0]["n"] == 3


def test_duplicate_events_across_and_within_batches(ref_db):
    ingest_trades(ref_db, "b1", "MOEX-ISS", [trade(1, "300"), trade(1, "300")])
    out = ingest_trades(ref_db, "b2", "MOEX-ISS", [trade(1, "300"), trade(2, "301")])
    assert out["accepted"] == 1 and out["duplicates"] == 1
    assert ref_db.rows("SELECT count() n FROM market_trades")[0]["n"] == 2


def test_decimal_precision_preserved(ref_db):
    ingest_trades(ref_db, "b1", "MOEX-ISS", [trade(1, "299.12345678")])
    p = ref_db.rows("SELECT price FROM market_trades")[0]["price"]
    assert p == Decimal("299.12345678")


# ---------- свечи и сигналы ----------

def _load_series(db, prices, ticker_id=SBER, start=1):
    rows = [trade(start + i, p, ticker_id=ticker_id, minute=0, second=i)
            for i, p in enumerate(prices)]
    ingest_trades(db, f"b{ticker_id}{start}", "MOEX-ISS", rows)


def test_ohlcv_values(ref_db):
    _load_series(ref_db, ["100", "105", "99", "102"])
    analytics.build_ohlcv(ref_db)
    c = ref_db.rows("SELECT * FROM agg_ohlcv_1m FINAL")[0]
    assert (c["open"], c["high"], c["low"], c["close"]) == (
        Decimal(100), Decimal(105), Decimal(99), Decimal(102))
    assert c["volume"] == 40 and c["trade_count"] == 4
    assert c["turnover"] == Decimal(10 * (100 + 105 + 99 + 102))


def test_open_close_ignore_arrival_order(ref_db):
    late_first = [trade(3, "110", second=30), trade(1, "100", second=1),
                  trade(2, "105", second=10)]
    ingest_trades(ref_db, "b1", "MOEX-ISS", late_first)
    analytics.build_ohlcv(ref_db)
    c = ref_db.rows("SELECT open, close FROM agg_ohlcv_1m FINAL")[0]
    assert (c["open"], c["close"]) == (Decimal(100), Decimal(110))


def test_ohlcv_recompute_does_not_duplicate_and_picks_up_late_trades(ref_db):
    _load_series(ref_db, ["100", "101"])
    analytics.build_ohlcv(ref_db)
    analytics.build_ohlcv(ref_db)
    ingest_trades(ref_db, "late", "MOEX-ISS", [trade(50, "120", second=50)])
    analytics.build_ohlcv(ref_db)
    rows = ref_db.rows("SELECT * FROM agg_ohlcv_1m FINAL")
    assert len(rows) == 1 and rows[0]["close"] == Decimal(120) and rows[0]["trade_count"] == 3


def test_candles_do_not_mix_tickers_or_sessions(ref_db):
    _load_series(ref_db, ["100", "101"], ticker_id=SBER)
    _load_series(ref_db, ["50", "51"], ticker_id=GAZP, start=100)
    analytics.build_ohlcv(ref_db)
    got = {r["ticker_id"]: r["close"] for r in ref_db.rows("SELECT * FROM agg_ohlcv_1m FINAL")}
    assert got == {SBER: Decimal(101), GAZP: Decimal(51)}


@pytest.mark.parametrize("prices,expected", [
    (["100", "101", "102", "103", "104"], "up"),
    (["100", "99", "98", "97", "96"], "down"),
    (["100", "100.2", "99.9", "100.1", "100.3"], "flat"),
    (["100", "130"], "insufficient_data"),
])
def test_signal_rules(ref_db, prices, expected):
    _load_series(ref_db, prices)
    analytics.build_ohlcv(ref_db)
    analytics.compute_signals(ref_db)
    s = analytics.get_signal(ref_db, SBER, SESSION)
    assert s["signal"] == expected and s["method_version"] == analytics.METHOD_VERSION


# ---------- рекомендации, роли, аудит ----------

@pytest.fixture
def with_signal(ref_db):
    _load_series(ref_db, ["100", "101", "102", "103", "104"])
    analytics.build_ohlcv(ref_db)
    analytics.compute_signals(ref_db)
    return ref_db


def test_recommendation_lifecycle(with_signal):
    db = with_signal
    rid = rec.draft(db, "anna", SBER, SESSION)
    assert rec.customer_report(db) == []          # черновик заказчику не виден
    with pytest.raises(ValueError):
        rec.publish(db, "boris", rid)              # без проверки публикация запрещена
    rec.review(db, "boris", rid, approve=True)
    rec.publish(db, "boris", rid)
    report = rec.customer_report(db)
    assert len(report) == 1
    r = report[0]
    assert (r["ticker"], r["action"], r["method_version"]) == ("SBER", "buy", "rules-v1")
    assert "user_id" not in r and "author" not in r


def test_author_cannot_review_own_and_rejected_not_published(with_signal):
    db = with_signal
    rid = rec.draft(db, "anna", SBER, SESSION)
    with pytest.raises(rec.Denied):
        rec.review(db, "anna", rid, approve=True)
    rec.review(db, "boris", rid, approve=False)
    with pytest.raises(ValueError):
        rec.publish(db, "boris", rid)
    assert rec.customer_report(db) == []


def test_no_recommendation_without_enough_data(ref_db):
    _load_series(ref_db, ["100", "130"])
    analytics.build_ohlcv(ref_db)
    analytics.compute_signals(ref_db)
    with pytest.raises(ValueError):
        rec.draft(ref_db, "anna", SBER, SESSION)


def test_roles_are_least_privilege():
    assert rec.ROLE_RIGHTS["customer"] == {"read_published"}
    for role, bad in [("analyst", "publish"), ("customer", "read_facts"),
                      ("data_engineer", "draft"), ("security_admin", "read_facts"),
                      ("analyst", "read_audit")]:
        with pytest.raises(rec.Denied):
            rec.require(role, bad)


def test_audit_trail_is_readable_only_by_security_admin(with_signal):
    db = with_signal
    rid = rec.draft(db, "anna", SBER, SESSION)
    rec.review(db, "boris", rid, True)
    rec.publish(db, "boris", rid)
    actions = [r["action"] for r in rec.read_audit(db, "security_admin")]
    assert actions == ["draft", "review_approved", "publish"]
    with pytest.raises(rec.Denied):
        rec.read_audit(db, "analyst")


# ---------- данные API Мосбиржи (формат ответа ISS) ----------

def test_moex_end_to_end(db):
    day = "2026-10-29"
    inst = moex.parse_instrument(moex_security_payload(), SBER, 1, day)
    assert inst["ticker"] == "SBER" and inst["currency"] == "SUR"
    load = load_reference(db, [moex.parse_session(day)], [inst])
    assert load["instruments"] == 1
    series = [(1000 + i, f"10:00:{i:02d}", 298.0 + i * 0.5, 10) for i in range(8)]
    rows = moex.parse_trades(moex_trades_payload(series), SBER)
    assert {"BUYSELL", "buysell"}.isdisjoint(rows[0])        # лишние поля не переносим
    out = ingest_trades(db, "moex-1", moex.SOURCE_ID, rows)
    assert out["accepted"] == 8 and out["rejected"] == 0
    analytics.build_ohlcv(db)
    analytics.compute_signals(db)
    assert analytics.get_signal(db, SBER, moex.session_id_for(day))["signal"] == "up"
