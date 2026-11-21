"""Консультирование на реальных дневных данных Мосбиржи (5 эмитентов, ~64 сессии)."""
import math
from datetime import date

import psycopg2
import pytest

from analytics_firm import advisory
from conftest import FIX

MOEX = FIX / "moex"
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "GMKN"]


def sql(pg, q, args=None):
    with pg.cursor() as cur:
        cur.execute(q, args)
        return cur.fetchall() if cur.description else None


def fails(pg, q, args=None):
    with pytest.raises(psycopg2.Error):
        sql(pg, q, args)
    pg.rollback()


@pytest.fixture
def world(pg, db):
    ids = advisory.seed_from_moex(pg, db, MOEX, TICKERS)
    sql(pg, "INSERT INTO advisory_clients VALUES (1,'client-A','conservative',365,30,'active'),"
            "(2,'client-B','aggressive',90,100,'active')")
    pg.commit()
    return pg, db, ids


def test_01_real_moex_history_loaded_into_both_stores(world):
    pg, db, ids = world
    n = db.rows("SELECT ticker_id, count() c, min(low) lo, "
                "countIf(high < low OR close > high OR close < low) bad "
                "FROM daily_bars FINAL GROUP BY ticker_id ORDER BY ticker_id")
    assert [r["ticker_id"] for r in n] == [1, 2, 3, 4, 5]
    assert all(r["c"] >= 60 and r["bad"] == 0 and r["lo"] > 0 for r in n)
    assert sql(pg, "SELECT count(*) FROM tickers")[0][0] == 5
    assert sql(pg, "SELECT currency FROM instruments WHERE instrument_id=1")[0][0] == "SUR "
    assert db.rows("SELECT count() c FROM ref_session_instruments FINAL")[0]["c"] >= 300


def test_02_reload_is_idempotent(world):
    pg, db, ids = world
    before = db.rows("SELECT count() c FROM daily_bars FINAL")[0]["c"]
    advisory.seed_from_moex(pg, db, MOEX, TICKERS)
    assert db.rows("SELECT count() c FROM daily_bars FINAL")[0]["c"] == before


def test_03_metrics_match_independent_calculation(world):
    pg, db, ids = world
    m = advisory.metrics(db, pg, ids["SBER"])
    rows = db.rows("SELECT close FROM daily_bars FINAL WHERE ticker_id=1 ORDER BY trade_date")
    c = [float(r["close"]) for r in rows][-21:]
    assert m["ret"] == pytest.approx(c[-1] / c[0] - 1)
    r = [math.log(b / a) for a, b in zip(c, c[1:])]
    mu = sum(r) / len(r)
    vol = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252)
    assert m["vol"] == pytest.approx(vol) and 0 <= m["max_drawdown"] < 1


def test_04_risk_class_thresholds():
    assert [advisory.risk_class(v) for v in (0.1, 0.3, 0.6)] == ["low", "medium", "high"]


def test_05_conservative_client_never_gets_buy_above_his_risk(world):
    pg, db, ids = world
    for secid, tid in ids.items():
        for asof in (date(2026, 9, 15), date(2026, 10, 1), date(2026, 10, 29)):
            rid = advisory.advise(pg, db, 1, tid, "anna", asof)
            action, rc = sql(pg, "SELECT action, risk_class FROM recommendations "
                                 "WHERE rec_id=%s", (rid,))[0]
            assert not (action == "buy" and rc != "low"), (secid, asof)


def test_06_position_limit_turns_buy_into_hold(world, monkeypatch):
    pg, db, ids = world
    monkeypatch.setattr(advisory, "MOM_THRESHOLD", -1.0)       # всегда buy по сигналу
    monkeypatch.setattr(advisory, "risk_class", lambda v: "low")
    sql(pg, "UPDATE advisory_clients SET max_position_pct=40 WHERE client_id=2")
    sql(pg, "INSERT INTO positions VALUES (2,1,1000,250),(2,2,1,100)")
    pg.commit()
    rid = advisory.advise(pg, db, 2, ids["SBER"], "anna")
    action, why = sql(pg, "SELECT action, rationale FROM recommendations WHERE rec_id=%s", (rid,))[0]
    assert action == "hold" and "лимита" in why
    rid2 = advisory.advise(pg, db, 2, ids["GAZP"], "anna")
    assert sql(pg, "SELECT action FROM recommendations WHERE rec_id=%s", (rid2,))[0][0] == "buy"


def test_07_split_adjustment_removes_artificial_drop(world):
    pg, db, ids = world
    raw = db.rows("SELECT trade_date, close FROM daily_bars FINAL WHERE ticker_id=1 "
                  "ORDER BY trade_date")
    ex = raw[30]["trade_date"]
    sql(pg, "INSERT INTO corporate_events VALUES (1,1,'split',%s,NULL,2)", (ex,))
    pg.commit()
    s, _ = advisory.series(db, pg, 1)
    assert s[29][1] == raw[29]["close"] / 2 and s[30][1] == raw[30]["close"]


def test_08_recommendations_are_immutable_and_status_log_append_only(world):
    pg, db, ids = world
    rid = advisory.advise(pg, db, 2, ids["SBER"], "anna")
    fails(pg, "UPDATE recommendations SET action='sell' WHERE rec_id=%s", (rid,))
    fails(pg, "DELETE FROM recommendations WHERE rec_id=%s", (rid,))
    fails(pg, "UPDATE recommendation_status_events SET status='published'")
    fails(pg, "INSERT INTO recommendations (rec_id,client_id,ticker_id,action,risk_class,"
              "method_version,data_cutoff,rationale,risk_disclosure,author) VALUES "
              "(gen_random_uuid(),2,1,'buy','low','v','2026-10-29','r',NULL,'a')")


def test_09_publication_workflow_and_client_report(world):
    pg, db, ids = world
    rid = advisory.advise(pg, db, 2, ids["LKOH"], "anna")
    assert advisory.client_report(pg, 2) == []
    with pytest.raises(ValueError):
        advisory.publish(pg, rid, "boris")
    with pytest.raises(PermissionError):
        advisory.review(pg, rid, "anna", True)
    advisory.review(pg, rid, "boris", True)
    advisory.publish(pg, rid, "boris")
    rep = advisory.client_report(pg, 2)
    assert len(rep) == 1 and rep[0]["ticker"] == "LKOH" and rep[0]["risk_disclosure"]
    assert not {"client_id", "author", "rec_id"} & set(rep[0])
    assert [r[0] for r in sql(pg, "SELECT status FROM recommendation_status_events "
                                  "ORDER BY event_id")] == ["draft", "approved", "published"]


def test_10_clients_never_reach_clickhouse_and_pg_rules_hold(world):
    pg, db, ids = world
    tables = db.tables()
    assert not {"advisory_clients", "positions", "customers", "owner_accounts"} & set(tables)
    assert not any("client" in c for cols in tables.values() for c in cols)
    fails(pg, "INSERT INTO advisory_clients VALUES (9,'x','reckless',30,10,'active')")
    fails(pg, "INSERT INTO advisory_clients VALUES (9,'x','moderate',30,0,'active')")
    fails(pg, "INSERT INTO corporate_events VALUES (5,1,'dividend','2026-10-01',NULL,NULL)")
    fails(pg, "INSERT INTO positions VALUES (1,1,-5,10)")
