"""Открытие и закрытие торговой сессии: что принимаем, что считаем, когда запускаемся."""
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analytics_firm import analytics, moex, sessions
from analytics_firm.loader import ingest_trades
from analytics_firm.reference import load_reference
from conftest import SBER, SESSION, instrument, trade


def at(h, m=0, s=0):
    return datetime(2026, 10, 29, h, m, s)


def row(n, price, when):
    return dict(trade(n, price), event_time=when)


def test_01_session_hours_are_inclusive_at_open_and_close(ref_db):      # 10:00 - 18:50
    rows = [row(1, "100", at(9, 59, 59)), row(2, "100", at(10, 0, 0)),
            row(3, "100", at(14, 0)), row(4, "100", at(18, 50, 0)), row(5, "100", at(18, 50, 1))]
    out = ingest_trades(ref_db, "h", "MOEX-ISS", rows)
    assert out["accepted"] == 3
    assert out["reject_rules"] == ["outside_session_hours", "outside_session_hours"]


def test_02_closed_session_does_not_accept_new_trades(ref_db):
    ingest_trades(ref_db, "a", "MOEX-ISS", [row(1, "100", at(11))])
    sessions.set_status(ref_db, SESSION, "closed")
    out = ingest_trades(ref_db, "b", "MOEX-ISS", [row(2, "101", at(12))])
    assert out["accepted"] == 0 and out["reject_rules"] == ["session_closed"]
    assert ref_db.rows("SELECT count() n FROM market_trades")[0]["n"] == 1


def test_03_close_session_builds_candles_and_signals(ref_db):
    prices = ["100", "101", "102", "103", "104"]
    ingest_trades(ref_db, "a", "MOEX-ISS",
                  [row(i + 1, p, at(10, 5 + i)) for i, p in enumerate(prices)])
    assert ref_db.rows("SELECT count() n FROM agg_ohlcv_1m")[0]["n"] == 0   # до закрытия расчётов нет
    out = sessions.close_session(ref_db, SESSION)
    assert len(out) == 1
    assert analytics.get_signal(ref_db, SBER, SESSION)["signal"] == "up"
    assert ref_db.rows("SELECT status FROM ref_sessions FINAL")[0]["status"] == "closed"


def test_04_closing_unknown_session_fails(ref_db):
    with pytest.raises(KeyError):
        sessions.close_session(ref_db, 12345)


def test_05_closing_one_session_leaves_the_other_open(ref_db):
    load_reference(ref_db, [{"session_id": 2, "session_date": "2026-10-29",
                             "start_at": "2026-10-29T19:05:00", "end_at": "2026-10-29T23:50:00",
                             "venue": "MOEX/EVE"}], [instrument(SBER, "SBER", session_id=2)])
    sessions.close_session(ref_db, SESSION)
    evening = dict(trade(1, "100"), session_id=2, event_time=at(20))
    out = ingest_trades(ref_db, "e", "MOEX-ISS", [evening])
    assert out["accepted"] == 1


def test_06_trade_in_main_hours_is_rejected_for_evening_session(ref_db):
    load_reference(ref_db, [{"session_id": 2, "session_date": "2026-10-29",
                             "start_at": "2026-10-29T19:05:00", "end_at": "2026-10-29T23:50:00",
                             "venue": "MOEX/EVE"}], [instrument(SBER, "SBER", session_id=2)])
    out = ingest_trades(ref_db, "x", "MOEX-ISS", [dict(trade(1, "100"), session_id=2,
                                                       event_time=at(11))])
    assert out["reject_rules"] == ["outside_session_hours"]


def test_07_full_day_replay_open_to_close(ref_db):
    day = [row(i, 100 + i * 0.1, datetime(2026, 10, 29, 10 + i // 60, i % 60))
           for i in range(0, 480, 20)]
    out = ingest_trades(ref_db, "day", "MOEX-ISS", day)
    assert out["rejected"] == 0
    sessions.close_session(ref_db, SESSION)
    first, last = day[0]["price"], day[-1]["price"]
    c = ref_db.rows("""SELECT argMin(open, minute) o, argMax(close, minute) c
                       FROM agg_ohlcv_1m FINAL""")[0]
    assert (c["o"], c["c"]) == (Decimal(str(first)), Decimal(str(last)))


def test_08_dag_runs_after_the_session_ends():
    cron = re.search(r'schedule="(\d+) (\d+) \* \* ([^"]+)"',
                     (Path(__file__).resolve().parent.parent / "dags" / "advisory_pipeline.py")
                     .read_text(encoding="utf-8"))
    minute, hour, weekdays = int(cron[1]), int(cron[2]), cron[3]
    end = datetime.fromisoformat(moex.parse_session("2026-10-29")["end_at"])
    assert (hour, minute) > (end.hour, end.minute)          # 19:00 позже закрытия в 18:50
    assert weekdays == "1-5"                                # торги по будням
