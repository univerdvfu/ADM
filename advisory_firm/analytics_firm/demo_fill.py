"""Наполнение демонстрационных баз, чтобы не было пустых таблиц.
Рыночные данные (бары, справочники, сырьё) — реальные, с Мосбиржи. Брокеры, заказчики, счета,
поручения, дивиденды и клиенты фирмы — выдуманные демо-данные, они нужны только для показа структуры.
"""
import math
import random
from datetime import datetime, timedelta
from decimal import Decimal

from . import advisory, analytics, jobs, recommendations as rec
from .reference import load_reference
from .stack import run_batch


def _pg(pg, sql, args=None):
    with pg.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else None


def fill_demo(pg, ch, s3, log, with_day=True):
    rnd = random.Random(2026)
    tickers = [r[0] for r in _pg(pg, "SELECT ticker_id FROM tickers ORDER BY 1")]

    # ---- брокеры, заказчики, аккаунты владельцев, поручения (внешний контур) ----
    _pg(pg, "INSERT INTO brokers VALUES (1,'Брокер «Альфа» (демо)','active'),(2,'Брокер «Бета» (демо)','active'),"
            "(3,'Брокер «Гамма» (демо)','suspended') ON CONFLICT DO NOTHING")
    for i in range(1, 7):
        _pg(pg, "INSERT INTO customers VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (i, (i - 1) % 3 + 1, f"заказчик-{i:03d}"))
    accounts = []
    for a in range(1, 9):
        cust = (a - 1) % 6 + 1
        accounts.append((a, cust, (cust - 1) % 3 + 1, tickers[(a - 1) % len(tickers)]))
        _pg(pg, "INSERT INTO owner_accounts VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", accounts[-1])
    last = {t: _pg(pg, "SELECT max(session_id) FROM session_instruments WHERE ticker_id=%s", (t,))[0][0] for t in tickers}
    close = {r["ticker_id"]: r["close"] for r in ch.rows(
        "SELECT ticker_id, argMax(close, trade_date) close FROM daily_bars FINAL GROUP BY ticker_id")}
    for n in range(1, 13):
        acc = accounts[(n - 1) % len(accounts)]
        t = acc[3]
        price = (close[t] * Decimal(str(round(rnd.uniform(0.97, 1.03), 4)))).quantize(Decimal("0.01")) if n % 3 else None
        _pg(pg, "INSERT INTO client_requests VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (n, acc[0], t, last[t], "buy" if n % 2 else "sell", rnd.choice([10, 50, 100, 200]), price))
    log("PostgreSQL: брокеры, заказчики, аккаунты владельцев, поручения (демо-данные)")

    # ---- клиенты фирмы, портфели, корпоративные события ----
    profiles = [("conservative", 365, 25), ("moderate", 180, 35), ("aggressive", 90, 60), ("moderate", 270, 40)]
    for i, (p, h, m) in enumerate(profiles, start=3):
        _pg(pg, "INSERT INTO advisory_clients VALUES (%s,%s,%s,%s,%s,'active') ON CONFLICT DO NOTHING",
            (i, f"client-{chr(64 + i)}", p, h, m))
    for c in range(1, 7):
        for t in rnd.sample(tickers, 3):
            _pg(pg, "INSERT INTO positions VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (c, t, rnd.choice([50, 100, 300, 500]), (close[t] * Decimal(str(round(rnd.uniform(0.85, 1.05), 3)))).quantize(Decimal("0.01"))))
    dates = [r[0] for r in _pg(pg, "SELECT DISTINCT session_date FROM trading_sessions ORDER BY 1")]
    for n, t in enumerate(tickers, start=1):
        _pg(pg, "INSERT INTO corporate_events VALUES (%s,%s,'dividend',%s,%s,NULL) ON CONFLICT DO NOTHING",
            (n, t, dates[len(dates) // 2 + n], Decimal(str(round(close[t] * Decimal("0.02"), 2)))))
    pg.commit()
    log("PostgreSQL: клиенты фирмы, портфели, корпоративные события (демо-данные)")

    # ---- пакет сделок с браком: сырьё в MinIO, задание и карантин в PostgreSQL ----
    day = _pg(pg, "SELECT max(session_date) FROM trading_sessions")[0][0]
    sid = int(f"{day:%Y%m%d}") + 1_000_000_000          # отдельная демонстрационная сессия
    ses_rows = ch.rows("SELECT count() n FROM ref_sessions FINAL WHERE session_id=%(s)s", {"s": sid})[0]["n"]
    if not ses_rows:
        load_reference(ch, [{"session_id": sid, "session_date": day, "start_at": f"{day}T10:00:00", "end_at": f"{day}T18:50:00",
                             "venue": "MOEX/TQBR (демо-пакет)", "status": "open"}],
                       [{"session_id": sid, "ticker_id": 1, "instrument_id": 1, "ticker": "SBER", "instrument_type": "stock",
                         "nominal_value": "3", "currency": "SUR", "lot_size": 1, "tick_size": "0.01"}])
    base_price = close[1]
    mk = lambda i, minute, price=None, **kw: dict({"source_id": "MOEX-ISS", "event_id": f"pk-{i}", "ticker_id": 1, "session_id": sid,
        "event_time": datetime(day.year, day.month, day.day, 10, 0) + timedelta(minutes=minute),
        "price": price if price is not None else base_price + Decimal(i % 5) / 100, "quantity": 10 + i}, **kw)
    rows = [mk(i, 5 * i) for i in range(1, 21)]
    rows += [mk(21, 30, user_id=777), mk(22, 40, account_id=5), mk(23, 50, ticker_id=99), mk(24, 60, price=Decimal(-5)),
             mk(25, 9 * 60 + 40), mk(1, 5)]                                        # час вне торгов и повтор события
    out = run_batch(pg, ch, s3, "demo-batch-1", "MOEX-ISS", rows)
    log(f"Пакет сделок: принято {out['accepted']}, дублей {out['duplicates']}, в карантин {out['rejected']} "
        f"(сырьё в MinIO, задание и карантин в PostgreSQL)" if not out.get("skipped_batch") else "Пакет сделок уже загружен")

    # ---- журнал рекомендаций ----
    jobs.refresh_recommendations(pg, ch)
    ids = [r[0] for r in _pg(pg, "SELECT rec_id::text FROM recommendations ORDER BY created_at, rec_id")]
    for i, rid in enumerate(ids):
        if _pg(pg, "SELECT count(*) FROM recommendation_status_events WHERE rec_id=%s", (rid,))[0][0] > 1:
            continue
        if i % 5 == 4:
            continue                                   # остаётся черновиком
        if i % 10 == 0:
            advisory.review(pg, rid, "boris", False)
            continue
        advisory.review(pg, rid, "boris", True)
        if i % 3 != 0:
            advisory.publish(pg, rid, "boris")
    log(f"PostgreSQL: журнал рекомендаций ({len(ids)}), статусы: черновик, отклонено, согласовано, опубликовано")

    # ---- ClickHouse: котировки, сигналы, аудит ----
    if with_day:
        trades = ch.rows("SELECT event_time, price FROM market_trades WHERE session_id=20990101 ORDER BY event_time")
        if trades and ch.rows("SELECT count() n FROM market_quotes")[0]["n"] == 0:
            quotes = [["MOEX-ISS", f"q-{i}", 1, 20990101, t["event_time"].replace(tzinfo=None), t["price"] - Decimal("0.01"),
                       t["price"] + Decimal("0.01"), 100 + i, 120 + i] for i, t in enumerate(trades)]
            ch.insert("market_quotes", ["source_id", "event_id", "ticker_id", "session_id", "event_time", "bid", "ask", "bid_qty", "ask_qty"], quotes)
            log(f"ClickHouse: {len(quotes)} котировок bid/ask (смоделированы вокруг цен сделок)")
        if ch.rows("SELECT count() n FROM recommendations")[0]["n"] == 0:
            try:
                rid = rec.draft(ch, "anna", 1, 20990101)
                rec.review(ch, "boris", rid, True)
                rec.publish(ch, "boris", rid)
                log("ClickHouse: рекомендация прежней версии, журнал аудита заполнен")
            except Exception as e:                      # нет достаточного сигнала
                log(f"ClickHouse: прежний журнал рекомендаций пропущен ({e})")
    fill_market_analysis_demo(ch, log)
    return True


def fill_market_analysis_demo(ch, log):
    """Непрерывные минутные серии для двух интерактивных аналитик, только DEMO-SIM."""
    if ch.rows("SELECT count() n FROM market_trades WHERE source_id='DEMO-SIM'")[0]["n"]:
        return
    last = ch.rows("SELECT max(trade_date) AS day FROM daily_bars FINAL WHERE ticker_id=1")[0]["day"]
    close = ch.rows("SELECT argMax(close, trade_date) AS price FROM daily_bars FINAL WHERE ticker_id=1")[0]["price"]
    base = float(close)
    columns = ["source_id", "event_id", "ticker_id", "session_id", "event_time", "price", "quantity"]
    total = 0
    for k in range(8):
        day = last - timedelta(days=8 - k)
        sid = 290000000000 + int(f"{day:%Y%m%d}")
        load_reference(ch, [{"session_id": sid, "session_date": day, "start_at": f"{day}T10:00:00",
                             "end_at": f"{day}T13:00:00", "venue": "DEMO-SIM (минутная история)", "status": "closed"}],
                       [{"session_id": sid, "ticker_id": 1, "instrument_id": 1, "ticker": "SBER", "instrument_type": "stock",
                         "nominal_value": "3", "currency": "SUR", "lot_size": 1, "tick_size": "0.01"}])
        rows = []
        previous = base * (1 + 0.001 * math.sin(k))
        for minute in range(180):
            progress = minute / 179
            if k in (2, 7):
                change = 0.04 * progress + 0.0015 * math.sin(minute * math.pi / 10)
            else:
                change = (k - 3.5) * 0.003 * progress + 0.004 * math.sin(minute * math.pi / 17 + k)
            price = base * (1 + change)
            volume = 80 + (minute * 7 + (0 if k in (2, 7) else k * 13)) % 90
            if k in (2, 7) and minute >= 150:
                volume *= 3
            for part, second in enumerate((5, 35)):
                quantity = volume if part == 0 else max(1, volume // 2)
                if k == 7 and minute in (20, 30, 40) and part == 0:
                    quantity = 15000 + minute * 10
                trade_price = Decimal(str(round(price + (-0.01 if part == 0 else 0.01), 2)))
                rows.append(["DEMO-SIM", f"sim-{sid}-{minute}-{part}", 1, sid,
                             datetime(day.year, day.month, day.day, 10, 0) + timedelta(minutes=minute, seconds=second),
                             trade_price, quantity])
            previous = price
        ch.insert("market_trades", columns, rows)
        analytics.build_ohlcv(ch, sid)
        total += len(rows)
    log(f"ClickHouse: 8 минутных сессий, {total} сделок DEMO-SIM для поиска аналогов и VWAP (смоделировано)")
