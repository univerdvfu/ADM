"""Дневные бары: проверка до записи, брак в карантин с кодом, остальное принимается."""
from datetime import date
from decimal import Decimal

import pytest

from analytics_firm import advisory, stack
from analytics_firm.contract import Reject, validate_bar
from analytics_firm.loader import classify_bars, ingest_bars
from analytics_firm.reference import load_reference
from conftest import FIX, SESSION, instrument, session

MOEX = FIX / "moex"


def bar(**kw):
    b = {"source_id": "MOEX-ISS", "ticker_id": 1, "session_id": SESSION, "trade_date": date(2026, 10, 29),
         "open": "100", "high": "105", "low": "99", "close": "102", "volume": 1000, "turnover": "101000", "num_trades": 40}
    b.update(kw)
    return b


@pytest.mark.parametrize("change,rule", [
    ({"user_id": 5}, "forbidden_field"),
    ({"comment": "x"}, "unknown_field"),
    ({"close": "1.123456789"}, "bad_price"),
    ({"open": "-1"}, "bad_price"),
    ({"high": "98"}, "high_below_low"),
    ({"close": "120"}, "price_outside_range"),
    ({"open": "98"}, "price_outside_range"),
    ({"volume": -5}, "bad_volume"),
    ({"num_trades": 2.5}, "bad_count"),
    ({"turnover": "abc"}, "bad_turnover"),
    ({"trade_date": "29 октября"}, "bad_date"),
])
def test_bar_rules(change, rule):
    with pytest.raises(Reject) as e:
        validate_bar(bar(**change))
    assert e.value.rule == rule


def test_valid_bar_passes():
    assert validate_bar(bar())["close"] == Decimal("102")


def test_bad_bars_never_reach_the_table(ref_db):
    rows = [bar(), bar(close="120"), bar(ticker_id=2), bar(ticker_id=9), bar(user_id=1), bar(ticker_id=1)]
    out = ingest_bars(ref_db, "b1", "MOEX-ISS", rows)
    assert (out["accepted"], out["duplicates"], out["rejected"]) == (2, 1, 3)
    assert sorted(out["reject_rules"]) == ["forbidden_field", "price_outside_range", "ticker_not_admitted_to_session"]
    assert ref_db.rows("SELECT count() n FROM daily_bars")[0]["n"] == 2
    assert ref_db.rows("SELECT count() n FROM daily_bars WHERE close=120")[0]["n"] == 0


def test_classify_gives_verdict_per_row(ref_db):
    verdicts, fresh = classify_bars(ref_db, "MOEX-ISS", [bar(), bar(high="1"), bar()])
    assert [v["verdict"] for v in verdicts] == ["accepted", "rejected", "duplicate"] and len(fresh) == 1


def test_same_batch_is_idempotent(ref_db):
    ingest_bars(ref_db, "b1", "MOEX-ISS", [bar()])
    assert ingest_bars(ref_db, "b1", "MOEX-ISS", [bar(), bar(ticker_id=2)])["skipped_batch"] is True
    assert ref_db.rows("SELECT count() n FROM daily_bars")[0]["n"] == 1


def test_job_and_quarantine_in_postgres(pg, ref_db):
    out = stack.run_bars_batch(pg, ref_db, "bars-1", "MOEX-ISS", "moex/test", [bar(), bar(close="120"), bar(user_id=3)])
    assert out["rejected"] == 2
    with pg.cursor() as cur:
        cur.execute("SELECT accepted, rejected, raw_object FROM ingest_jobs WHERE batch_id='bars-1'")
        assert cur.fetchone() == (1, 2, "moex/test")
        cur.execute("SELECT rule FROM quarantine WHERE batch_id='bars-1' ORDER BY row_no")
        assert [r[0] for r in cur.fetchall()] == ["price_outside_range", "forbidden_field"]


def test_real_moex_bars_all_pass_the_contract(pg, db):
    report = {}
    advisory.seed_from_moex(pg, db, MOEX, ["SBER", "GAZP", "LKOH", "ROSN", "GMKN"], report)
    assert report["rejected"] == 0 and report["accepted"] >= 300
    assert db.rows("SELECT count() n FROM daily_bars FINAL")[0]["n"] == report["accepted"]
