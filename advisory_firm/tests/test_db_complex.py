"""15 тестов: БД предметной области справляется со сложными задачами.
PostgreSQL: агрегаты, транзакции, конкурентность, ссылочная целостность, оконные функции, объём.
ClickHouse: окна по реальным барам, ASOF JOIN, большой объём, дедупликация версий, партиции.
Между хранилищами: согласованность справочников и сверка сделок со свечами."""
import random
import re
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg2
import pytest

from analytics_firm import advisory, analytics
from analytics_firm.loader import ingest_trades
from analytics_firm.reference import load_reference
from conftest import FIX, instrument

MOEX = FIX / "moex"
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "GMKN"]
TRADE_COLS = ["source_id", "event_id", "ticker_id", "session_id", "event_time", "price", "quantity"]


def sql(pg, q, args=None):
    with pg.cursor() as cur:
        cur.execute(q, args)
        return cur.fetchall() if cur.description else None


@pytest.fixture
def world(pg, db):
    ids = advisory.seed_from_moex(pg, db, MOEX, TICKERS)
    return pg, db, ids


# ===================== PostgreSQL =====================

def test_01_portfolio_by_issuer_with_grouping_sets(world):
    pg, db, ids = world
    sql(pg, "INSERT INTO advisory_clients VALUES (1,'a','moderate',90,50,'active'),"
            "(2,'b','aggressive',30,100,'active')")
    sql(pg, "INSERT INTO positions VALUES (1,1,100,250),(1,2,50,120),(2,1,10,260),(2,3,5,6500),(2,4,40,480)")
    rows = sql(pg, """SELECT c.alias, i.issuer_id, SUM(p.quantity * p.avg_price)
        FROM positions p JOIN advisory_clients c USING (client_id) JOIN tickers t USING (ticker_id)
        JOIN instruments x USING (instrument_id) JOIN issuers i USING (issuer_id)
        GROUP BY GROUPING SETS ((c.alias, i.issuer_id), (c.alias), ())""")
    got = {(a, i): v for a, i, v in rows}
    assert got[("a", 1)] == 25000 and got[("a", 2)] == 6000 and got[("b", 3)] == 32500
    assert got[("a", None)] == 31000 and got[("b", None)] == 54300 and got[(None, None)] == 85300


def test_02_failed_transaction_rolls_back_all_changes(world):
    pg, db, ids = world
    sql(pg, "INSERT INTO brokers VALUES (1,'B','active')")
    pg.commit()
    with pytest.raises(psycopg2.Error):
        sql(pg, "INSERT INTO customers VALUES (1,1,'c')")
        sql(pg, "INSERT INTO owner_accounts VALUES (1,1,1,1)")
        sql(pg, "INSERT INTO client_requests VALUES (1,1,1,99999999,'buy',1,NULL)")   # сессии нет
    pg.rollback()
    assert sql(pg, "SELECT (SELECT count(*) FROM customers), (SELECT count(*) FROM owner_accounts)")[0] == (0, 0)


def test_03_concurrent_inserts_of_one_ticker_only_one_wins(world):
    pg, db, ids = world
    results, barrier = [], threading.Barrier(8)

    def worker(i):
        c = psycopg2.connect(pg.dsn)
        try:
            barrier.wait()
            with c.cursor() as cur:
                cur.execute("INSERT INTO tickers VALUES (%s, 1, 'NEWT')", (100 + i,))
            c.commit()
            results.append("ok")
        except psycopg2.errors.UniqueViolation:
            c.rollback()
            results.append("dup")
        finally:
            c.close()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 1 and results.count("dup") == 7
    assert sql(pg, "SELECT count(*) FROM tickers WHERE ticker='NEWT'")[0][0] == 1


def test_04_referential_integrity_blocks_dangerous_deletes(world):
    pg, db, ids = world
    sql(pg, "INSERT INTO brokers VALUES (1,'B','active'),(2,'unused','active')")
    sql(pg, "INSERT INTO customers VALUES (1,1,'c')")
    pg.commit()
    for q in ("DELETE FROM brokers WHERE broker_id=1", "DELETE FROM tickers WHERE ticker_id=1",
              "DELETE FROM trading_sessions WHERE session_id=(SELECT min(session_id) FROM trading_sessions)",
              "DELETE FROM issuers WHERE issuer_id=1"):
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            sql(pg, q)
        pg.rollback()
    sql(pg, "DELETE FROM brokers WHERE broker_id=2")                  # незанятого брокера удалить можно
    assert sql(pg, "SELECT count(*) FROM brokers")[0][0] == 1


def test_05_latest_status_per_recommendation_with_distinct_on(world):
    pg, db, ids = world
    sql(pg, "INSERT INTO advisory_clients VALUES (1,'a','moderate',90,50,'active')")
    for n in "abc":
        sql(pg, "INSERT INTO recommendations VALUES (%s::uuid,1,1,'hold','low','v','2026-10-29','r','d','x')",
            (n * 8 + "-0000-0000-0000-" + n * 12,))
    flow = {"a": ["draft", "approved", "published"], "b": ["draft", "rejected"], "c": ["draft"]}
    for n in ("c", "a", "b"):                                          # вперемешку
        for st in flow[n]:
            sql(pg, "INSERT INTO recommendation_status_events (rec_id,status,actor) VALUES (%s::uuid,%s,'u')",
                (n * 8 + "-0000-0000-0000-" + n * 12, st))
    latest = dict(sql(pg, """SELECT DISTINCT ON (rec_id) left(rec_id::text,1), status
                             FROM recommendation_status_events ORDER BY rec_id, event_id DESC"""))
    assert latest == {"a": "published", "b": "rejected", "c": "draft"}


def test_06_window_functions_over_corporate_events(world):
    pg, db, ids = world
    ev = [(1, 1, "2026-03-01", 10), (2, 1, "2026-06-01", 12), (3, 1, "2026-09-01", 15),
          (4, 2, "2026-04-01", 5), (5, 2, "2026-10-01", 7)]
    for e in ev:
        sql(pg, "INSERT INTO corporate_events VALUES (%s,%s,'dividend',%s,%s,NULL)", e)
    rows = sql(pg, """SELECT ticker_id, ex_date, amount,
            SUM(amount) OVER (PARTITION BY ticker_id ORDER BY ex_date) AS running,
            amount / LAG(amount) OVER (PARTITION BY ticker_id ORDER BY ex_date) - 1 AS growth,
            ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY ex_date DESC) AS rn
        FROM corporate_events ORDER BY ticker_id, ex_date""")
    assert [r[3] for r in rows] == [10, 22, 37, 5, 12]
    assert rows[0][4] is None and rows[1][4] == Decimal("0.2") and rows[2][4] == Decimal("0.25")
    assert [r[0] for r in rows if r[5] == 1] == [1, 2] and [r[2] for r in rows if r[5] == 1] == [15, 7]


def test_07_hundred_thousand_positions_use_index_and_sum_correctly(world):
    pg, db, ids = world
    sql(pg, "INSERT INTO advisory_clients SELECT g,'u'||g,'moderate',90,50,'active' FROM generate_series(1,20000) g")
    sql(pg, "INSERT INTO positions SELECT c.client_id, t.ticker_id, (c.client_id % 100) + 1, 100 + t.ticker_id "
            "FROM advisory_clients c CROSS JOIN tickers t")
    sql(pg, "ANALYZE positions")
    pg.commit()
    assert sql(pg, "SELECT count(*) FROM positions")[0][0] == 100000
    plan = "\n".join(r[0] for r in sql(pg, "EXPLAIN SELECT * FROM positions WHERE client_id = 777"))
    assert "Index" in plan and "Seq Scan" not in plan
    expected = sum(((c % 100) + 1) * (100 + t) for c in range(1, 20001) for t in range(1, 6))
    assert sql(pg, "SELECT SUM(quantity * avg_price) FROM positions")[0][0] == expected


# ===================== ClickHouse =====================

def test_08_window_functions_on_real_bars_match_python(world):
    pg, db, ids = world
    rows = db.rows("""SELECT trade_date, toFloat64(close) AS c,
          avg(toFloat64(close)) OVER (PARTITION BY ticker_id ORDER BY trade_date
                                      ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
          toFloat64(close) / lagInFrame(toFloat64(close), 1, toFloat64(close)) OVER (
              PARTITION BY ticker_id ORDER BY trade_date
              ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1 AS r
        FROM daily_bars FINAL WHERE ticker_id = 1 ORDER BY trade_date""")
    c = [r["c"] for r in rows]
    assert len(c) >= 60
    for i in (4, 10, 30, len(c) - 1):
        assert rows[i]["ma5"] == pytest.approx(sum(c[i - 4:i + 1]) / 5)
        assert rows[i]["r"] == pytest.approx(c[i] / c[i - 1] - 1)
    assert rows[0]["r"] == pytest.approx(0)


def test_09_rank_tickers_by_return_matches_python(world):
    pg, db, ids = world
    rows = db.rows("""SELECT ticker_id, ret, rank() OVER (ORDER BY ret DESC) AS rnk FROM (
          SELECT ticker_id, toFloat64(argMax(close, trade_date)) / toFloat64(argMin(close, trade_date)) - 1 AS ret
          FROM (SELECT ticker_id, trade_date, close,
                       row_number() OVER (PARTITION BY ticker_id ORDER BY trade_date DESC) AS rn
                FROM daily_bars FINAL) WHERE rn <= 21 GROUP BY ticker_id) ORDER BY rnk""")
    expect = {}
    for t in ids.values():
        cl = [float(r["close"]) for r in db.rows(
            "SELECT close FROM daily_bars FINAL WHERE ticker_id=%(t)s ORDER BY trade_date", {"t": t})][-21:]
        expect[t] = cl[-1] / cl[0] - 1
    assert [r["ticker_id"] for r in rows] == sorted(expect, key=expect.get, reverse=True)
    assert all(r["ret"] == pytest.approx(expect[r["ticker_id"]]) for r in rows)


def test_10_asof_join_attaches_the_latest_quote_to_each_trade(db):
    t0 = datetime(2026, 10, 29, 10, 0, 0)
    sec = lambda s: t0 + timedelta(seconds=s)
    db.insert("market_quotes", ["source_id", "event_id", "ticker_id", "session_id", "event_time", "bid", "ask", "bid_qty", "ask_qty"],
              [["S", "q1", 1, 1, sec(0), Decimal(99), Decimal(101), 1, 1], ["S", "q2", 1, 1, sec(10), Decimal(100), Decimal(102), 1, 1],
               ["S", "q3", 1, 1, sec(20), Decimal(101), Decimal(103), 1, 1]])
    db.insert("market_trades", TRADE_COLS,
              [["S", "t0", 1, 1, sec(-1), Decimal(100), 1], ["S", "t1", 1, 1, sec(5), Decimal(100), 1],
               ["S", "t2", 1, 1, sec(15), Decimal(100), 1], ["S", "t3", 1, 1, sec(25), Decimal(100), 1],
               ["S", "t4", 2, 1, sec(5), Decimal(100), 1]])
    rows = db.rows("""SELECT t.event_id AS e, q.bid AS bid, q.ask AS ask FROM market_trades t
        ASOF LEFT JOIN market_quotes q ON t.ticker_id = q.ticker_id AND t.event_time >= q.event_time
        ORDER BY e SETTINGS join_use_nulls = 1""")
    got = {r["e"]: (r["bid"], r["ask"]) for r in rows}
    assert got == {"t0": (None, None), "t1": (99, 101), "t2": (100, 102), "t3": (101, 103), "t4": (None, None)}


def test_11_two_hundred_thousand_shuffled_trades_aggregate_correctly(db):
    rnd = random.Random(11)
    base = datetime(2026, 10, 29, 10, 0, 0)
    rows, exp = [], {}
    for i in range(200_000):
        when = base + timedelta(seconds=rnd.randrange(0, 8 * 3600), microseconds=i)
        price, qty = Decimal(rnd.randrange(29000, 30000)) / 100, rnd.randrange(1, 50)
        rows.append(["S", f"e{i:07d}", 1, 1, when, price, qty])
        m = exp.setdefault(when.replace(second=0, microsecond=0), [])
        m.append((when, f"e{i:07d}", price, qty))
    rnd.shuffle(rows)
    for k in range(0, len(rows), 50_000):
        db.insert("market_trades", TRADE_COLS, rows[k:k + 50_000])
    started = time.time()
    analytics.build_ohlcv(db)
    assert time.time() - started < 30
    got = {r["minute"].replace(tzinfo=None): r for r in db.rows("SELECT * FROM agg_ohlcv_1m FINAL")}
    assert len(got) == len(exp)
    assert sum(r["volume"] for r in got.values()) == sum(q for v in exp.values() for *_, q in v)
    for minute in rnd.sample(sorted(exp), 40):
        v = sorted(exp[minute])
        g = got[minute]
        assert (g["open"], g["close"]) == (v[0][2], v[-1][2])
        assert (g["high"], g["low"]) == (max(x[2] for x in v), min(x[2] for x in v))
        assert g["trade_count"] == len(v) and g["turnover"] == sum(x[2] * x[3] for x in v)


def test_12_corrected_bar_replaces_old_version_and_optimize_compacts(world):
    pg, db, ids = world
    before = db.rows("SELECT count() n FROM daily_bars FINAL")[0]["n"]
    bar = db.rows("SELECT * FROM daily_bars FINAL WHERE ticker_id=1 ORDER BY trade_date DESC LIMIT 1")[0]
    fixed = dict(bar, close=bar["close"] + 1, high=bar["high"] + 1, loaded_at=datetime.utcnow() + timedelta(seconds=5))
    db.insert("daily_bars", list(fixed), [list(fixed.values())])
    assert db.rows("SELECT count() n FROM daily_bars")[0]["n"] == before + 1           # две версии физически
    assert db.rows("SELECT count() n FROM daily_bars FINAL")[0]["n"] == before         # FINAL видит одну
    now = db.rows("SELECT close FROM daily_bars FINAL WHERE ticker_id=1 ORDER BY trade_date DESC LIMIT 1")[0]
    assert now["close"] == bar["close"] + 1
    db.command("OPTIMIZE TABLE daily_bars FINAL")
    assert db.rows("SELECT count() n FROM daily_bars")[0]["n"] == before


def test_13_monthly_partitions_are_pruned_by_the_query(db):
    for month in (1, 2, 3):
        rows = [["S", f"m{month}-{i}", 1, 1, datetime(2026, month, 1 + i % 20, 11, 0, i % 60), Decimal(100), 1]
                for i in range(1000)]
        db.insert("market_trades", TRADE_COLS, rows)
    parts = {r["partition"] for r in db.rows(
        "SELECT DISTINCT partition FROM system.parts WHERE database=%(d)s AND table='market_trades' AND active",
        {"d": db.database})}
    assert parts == {"202601", "202602", "202603"}
    q = "SELECT sum(quantity) FROM market_trades WHERE event_time >= '2026-02-01' AND event_time < '2026-03-01'"
    assert db.command(q) == 1000
    plan = "\n".join(r[0] if isinstance(r, (list, tuple)) else str(r) for r in db.client.query("EXPLAIN indexes = 1 " + q).result_rows)
    assert re.search(r"Parts:\s*1/3", plan), plan


# ===================== Между хранилищами =====================

def test_14_reference_data_is_identical_in_postgres_and_clickhouse(world):
    pg, db, ids = world
    pgrows = {(s, t): (nom, cur.strip(), lot) for s, t, nom, cur, lot in sql(pg, """
        SELECT si.session_id, si.ticker_id, i.nominal_value, i.currency, si.lot_size
        FROM session_instruments si JOIN tickers t USING (ticker_id) JOIN instruments i USING (instrument_id)""")}
    chrows = {}
    for r in db.rows("SELECT session_id, ticker_id, nominal_value, currency, lot_size FROM ref_session_instruments FINAL"):
        cur = r["currency"].decode() if isinstance(r["currency"], bytes) else r["currency"]
        chrows[(r["session_id"], r["ticker_id"])] = (r["nominal_value"], cur.strip("\x00 "), r["lot_size"])
    assert pgrows == chrows and len(pgrows) >= 300
    bars = {(r["session_id"], r["ticker_id"]) for r in db.rows("SELECT session_id, ticker_id FROM daily_bars FINAL")}
    assert bars == set(pgrows)                                        # у каждого бара есть допуск в PostgreSQL


def test_15_trades_reconcile_with_candles_after_shuffles_duplicates_and_late_rows(db):
    rnd = random.Random(15)
    days = [date(2026, 10, d) for d in (27, 28, 29)]
    sids = [int(d.strftime("%Y%m%d")) for d in days]
    load_reference(db, [{"session_id": s, "session_date": d, "start_at": f"{d}T10:00:00", "end_at": f"{d}T18:50:00",
                         "venue": "MOEX/TQBR"} for s, d in zip(sids, days)],
                   [instrument(1, "SBER", session_id=s) for s in sids])
    trades = []
    for s, d in zip(sids, days):
        for i in range(1000):
            when = datetime(d.year, d.month, d.day, 10) + timedelta(seconds=rnd.randrange(0, 8 * 3600 + 3000))
            trades.append({"source_id": "MOEX-ISS", "event_id": f"{s}-{i}", "ticker_id": 1, "session_id": s,
                           "event_time": when, "price": Decimal(rnd.randrange(29000, 30000)) / 100, "quantity": rnd.randrange(1, 100)})
    rnd.shuffle(trades)
    first = ingest_trades(db, "all", "MOEX-ISS", trades)
    replay = rnd.sample(trades, 900)
    late = [dict(trades[0], event_id="late-1", event_time=datetime(2026, 10, 27, 23, 0)),
            dict(trades[1], event_id="late-2", event_time=datetime(2026, 10, 28, 9, 0))]
    second = ingest_trades(db, "replay", "MOEX-ISS", replay + late)
    assert first["accepted"] + first["rejected"] == 3000
    assert (second["accepted"], second["duplicates"], second["rejected"]) == (0, 900, 2)
    assert second["reject_rules"] == ["outside_session_hours"] * 2
    ok = [t for t in trades if t["event_time"].time() <= datetime(2000, 1, 1, 18, 50).time()]
    assert first["accepted"] == len(ok)
    analytics.build_ohlcv(db)
    for s in sids:
        exp = sum(t["quantity"] for t in ok if t["session_id"] == s)
        got = db.rows("SELECT sum(volume) v FROM agg_ohlcv_1m FINAL WHERE session_id=%(s)s", {"s": s})[0]["v"]
        raw = db.rows("SELECT sum(quantity) v FROM market_trades WHERE session_id=%(s)s", {"s": s})[0]["v"]
        assert got == exp == raw
