from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from analytics_firm import market_analysis

CANDLE_COLS = ["ticker_id", "session_id", "minute", "open", "high", "low", "close",
               "volume", "trade_count", "turnover", "computed_at"]
TRADE_COLS = ["source_id", "event_id", "ticker_id", "session_id", "event_time", "price", "quantity"]


def candle(sid, minute, price, volume=100):
    price = Decimal(str(price))
    return [1, sid, minute, price, price * Decimal("1.001"), price * Decimal("0.999"), price, volume, 2,
            price * volume, datetime(2026, 1, 1)]


def test_twins_find_scaled_clone_and_future_returns(db):
    rows = []
    for sid, base in ((1, 100), (2, 40), (3, 250)):
        start = datetime(2026, 1, sid, 10)
        for i in range(80):
            change = i * 0.001 if sid != 2 else 0.002 * ((i % 7) - 3)
            rows.append(candle(sid, start + timedelta(minutes=i), base * (1 + change), 100 + i % 5))
    db.insert("agg_ohlcv_1m", CANDLE_COLS, rows)
    end = datetime(2026, 1, 3, 10) + timedelta(minutes=19)
    out = market_analysis.find_twins(db, 1, 3, end, length=20)
    assert out["target"]["return"] == pytest.approx(1.019 - 1, abs=0.00001)
    assert out["matches"][0]["session_id"] == 1
    assert out["matches"][0]["score"] == pytest.approx(100, abs=0.01)
    assert out["matches"][0]["outcomes"]["5"] == pytest.approx(1.024 / 1.019 - 1, abs=0.00001)
    assert len(out["matches"][0]["candles"]) == 50


def test_twins_reject_short_or_gapped_target(db):
    start = datetime(2026, 1, 1, 10)
    db.insert("agg_ohlcv_1m", CANDLE_COLS,
              [candle(1, start + timedelta(minutes=i * 2), 100 + i) for i in range(20)])
    with pytest.raises(ValueError, match="пропущенные минуты"):
        market_analysis.find_twins(db, 1, 1, start + timedelta(minutes=38), length=15)
    with pytest.raises(ValueError, match="только 5"):
        market_analysis.find_twins(db, 1, 1, start + timedelta(minutes=8), length=15)


def test_butterfly_recomputes_vwap_and_turnover_share(db):
    start = datetime(2026, 10, 29, 10)
    rows = [["MOEX-ISS", str(i), 1, 1, start + timedelta(seconds=i), Decimal(100), 10]
            for i in range(99)]
    rows.append(["MOEX-ISS", "big", 1, 1, start + timedelta(seconds=99), Decimal(110), 1000])
    db.insert("market_trades", TRADE_COLS, rows)
    out = market_analysis.butterfly_effect(db, 1, 1, top_percent=1)
    expected = (Decimal(99 * 100 * 10) + Decimal(110 * 1000)) / Decimal(99 * 10 + 1000)
    assert out["top_count"] == 1
    assert out["vwap"] == pytest.approx(float(expected))
    assert out["without_top_vwap"] == 100
    assert out["difference"] == pytest.approx(float(expected - 100))
    assert out["top_turnover_share_pct"] == pytest.approx(110000 / 209000 * 100)
    assert out["top_trades"][0]["event_id"] == "big"


def test_butterfly_respects_interval(db):
    start = datetime(2026, 10, 29, 10)
    rows = [["MOEX-ISS", str(i), 1, 1, start + timedelta(minutes=i), Decimal(100 + i), 10]
            for i in range(3)]
    db.insert("market_trades", TRADE_COLS, rows)
    out = market_analysis.butterfly_effect(db, 1, 1, start=start + timedelta(minutes=1),
                                           end=start + timedelta(minutes=2), top_percent=1)
    assert out["trade_count"] == 2
    assert out["vwap"] == 101.5
    assert out["start"] == start + timedelta(minutes=1)
    assert out["end"] == start + timedelta(minutes=2)


def test_market_sessions_joins_references_and_trade_counts(db):
    from analytics_firm.reference import load_reference
    from conftest import SESSION, instrument, session

    load_reference(db, [session()], [instrument(1, "SBER")])
    start = datetime(2026, 10, 29, 10)
    db.insert("agg_ohlcv_1m", CANDLE_COLS,
              [candle(SESSION, start + timedelta(minutes=i), 100 + i) for i in range(20)])
    db.insert("market_trades", TRADE_COLS,
              [["MOEX-ISS", "1", 1, SESSION, start, Decimal(100), 10]])
    out = market_analysis.market_sessions(db, 1)
    assert len(out) == 1
    assert out[0]["ticker"] == "SBER" and out[0]["minutes"] == 20 and out[0]["trades"] == 1
