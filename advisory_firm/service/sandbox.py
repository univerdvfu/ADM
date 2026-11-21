"""Песочница: подать свой пакет сделок «как от биржи» и посмотреть, как отреагирует каждая часть системы."""
import json
import time
from datetime import datetime

from analytics_firm import analytics, jobs, moex, sessions
from analytics_firm.loader import classify_rows
from analytics_firm.reference import load_reference
from analytics_firm.stack import RAW_BUCKET, run_batch

SID = 20990103
DAY = "2026-10-29"
SOURCE = "MOEX-ISS"
MAX_ROWS = 5000

RULES_RU = {
    "forbidden_field": "В записи есть ID человека (user_id, account_id, broker_id…): биржа не должна передавать нам персональные данные",
    "unknown_field": "В записи есть поле, которого нет в разрешённом списке",
    "missing_field": "Не хватает обязательного поля",
    "empty_key": "Пустой source_id или event_id",
    "bad_ticker_id": "ticker_id не целое положительное число",
    "bad_session_id": "session_id не целое положительное число",
    "bad_time": "Время сделки не разобрать",
    "bad_price": "Цена не положительная или не умещается в Decimal(20,8)",
    "bad_quantity": "Количество не целое положительное",
    "foreign_source": "Источник записи не совпадает с источником пакета",
    "unknown_session": "Такой торговой сессии нет",
    "ticker_not_admitted_to_session": "Эта бумага не допущена к этой сессии",
    "session_closed": "Сессия закрыта: новые сделки не принимаются",
    "outside_session_hours": "Время вне часов торгов 10:00–18:50",
    "bad_record": "Запись не является объектом",
}


def ensure(ch):
    if not ch.rows("SELECT count() n FROM ref_sessions FINAL WHERE session_id=%(s)s", {"s": SID})[0]["n"]:
        load_reference(ch, [{"session_id": SID, "session_date": DAY, "start_at": f"{DAY}T10:00:00",
                             "end_at": f"{DAY}T18:50:00", "venue": "MOEX/TQBR (песочница)", "status": "open"}],
                       [{"session_id": SID, "ticker_id": 1, "instrument_id": 1, "ticker": "SBER", "instrument_type": "stock",
                         "nominal_value": "3", "currency": "SUR", "lot_size": 1, "tick_size": "0.01"}])


def presets():
    n = int(time.time())

    def mk(i, hh, mm, ss=0, price="298.50", qty=10, tag="s", **kw):
        r = {"source_id": SOURCE, "event_id": f"{tag}{n}-{i}", "ticker_id": 1, "session_id": SID,
             "event_time": f"{DAY}T{hh:02d}:{mm:02d}:{ss:02d}", "price": price, "quantity": qty}
        r.update(kw)
        return r
    clean = [mk(i, 10, i * 5, price=f"{298 + i * 0.1:.2f}") for i in range(1, 9)]
    ids = [mk(1, 10, 5), mk(2, 10, 10), mk(3, 10, 15), mk(4, 10, 20, user_id=777), mk(5, 10, 25, account_id=42),
           mk(6, 10, 30, broker_id=3), mk(7, 10, 35, comment="лишнее поле")]
    hours = [mk(1, 9, 59, 59), mk(2, 10, 0, 0), mk(3, 14, 0), mk(4, 18, 50, 0), mk(5, 18, 50, 1), mk(6, 23, 0)]
    dups = [mk(1, 10, 5, tag="d"), mk(2, 10, 6, tag="d"), mk(2, 10, 6, tag="d"), mk(3, 10, 7, tag="d"), mk(1, 10, 5, tag="d")]
    bad = [mk(1, 11, 0, price="-5"), mk(2, 11, 1, price="0"), mk(3, 11, 2, price="abc"), mk(4, 11, 3, price="1.123456789"),
           mk(5, 11, 4, qty=0), mk(6, 11, 5, qty=2.5), mk(7, 11, 6, price="299.10"), dict(mk(8, 11, 7), event_time="вчера вечером")]
    unknown = [mk(1, 12, 0), mk(2, 12, 1, ticker_id=99), mk(3, 12, 2, session_id=123), mk(4, 12, 3, source_id="OTHER")]
    mix = clean[:3] + ids[3:5] + hours[:2] + dups[:2] + bad[:2] + unknown[1:3]
    iss = {"trades": {"columns": ["TRADENO", "TRADETIME", "SECID", "PRICE", "QUANTITY", "TRADEDATE", "BUYSELL"],
                      "data": [[n * 10 + k, t, "SBER", p, q, DAY, "B"] for k, (t, p, q) in enumerate([
                          ("10:00:03", 298.11, 120), ("10:15:41", 298.60, 50), ("12:30:00", 297.90, 300),
                          ("15:45:10", 294.00, 80), ("18:49:59", 295.08, 40), ("19:05:00", 295.20, 10)])]}}
    return {
        "clean": ("Чистый пакет", "8 нормальных сделок. Ожидаем: все приняты.", clean),
        "ids": ("Чужие ID в записях", "3 хороших записи и 4 с user_id, account_id, broker_id и лишним полем. Ожидаем: 4 отклонения.", ids),
        "hours": ("Вне часов торгов", "Сделки до открытия, на границах 10:00 и 18:50, после окончания и ночью.", hours),
        "dups": ("Дубли", "Один и тот же event_id приходит повторно. Ожидаем: повторы не попадают в базу.", dups),
        "bad": ("Плохие цены и количества", "Отрицательная и нулевая цена, текст вместо числа, 9 знаков после запятой, нулевое и дробное количество, мусорное время.", bad),
        "unknown": ("Неизвестная бумага, сессия, источник", "Тикер 99, сессия 123, источник OTHER.", unknown),
        "mix": ("Всё вместе", "Смесь хороших и разных плохих записей.", mix),
        "iss": ("Формат ISS (как отдаёт биржа)", "Таблица trades в формате Мосбиржи, поле BUYSELL (покупатель/продавец) мы не переносим; последняя сделка после закрытия торгов.", iss),
    }


def parse(text):
    obj = json.loads(text) if isinstance(text, (str, bytes)) else text
    if isinstance(obj, dict) and "trades" in obj:
        rows = moex.parse_trades(obj, 1)
        for r in rows:
            r["session_id"] = SID if r["event_time"].strftime("%Y-%m-%d") == DAY else r["session_id"]
        return rows
    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list):
        raise ValueError("Нужен список записей или объект с таблицей trades")
    if len(obj) > MAX_ROWS:
        raise ValueError(f"Не больше {MAX_ROWS} записей")
    return obj


def verdict_rows(raw, verdicts):
    out = []
    for v in verdicts:
        r = raw[v["n"]] if isinstance(raw[v["n"]], dict) else {}
        out.append({"n": v["n"] + 1, "verdict": v["verdict"], "rule": v["rule"],
                    "why": RULES_RU.get(v["rule"], "") if v["rule"] else ("Такой event_id уже есть в базе или раньше в этом пакете" if v["verdict"] == "duplicate" else "Прошла все проверки"),
                    "event_id": str(r.get("event_id", "")), "time": str(r.get("event_time", "")), "price": str(r.get("price", "")),
                    "qty": str(r.get("quantity", ""))})
    return out


def summary(verdicts):
    return {k: sum(1 for v in verdicts if v["verdict"] == k) for k in ("accepted", "duplicate", "rejected")}


def counts(ch, pg, s3):
    c = {"market_trades (ClickHouse)": ch.rows("SELECT count() n FROM market_trades WHERE session_id=%(s)s", {"s": SID})[0]["n"],
         "ingest_batches (ClickHouse)": ch.rows("SELECT count() n FROM ingest_batches WHERE batch_id LIKE 'sandbox-%'")[0]["n"],
         "ingest_rejects (ClickHouse)": ch.rows("SELECT count() n FROM ingest_rejects WHERE batch_id LIKE 'sandbox-%'")[0]["n"],
         "свечи agg_ohlcv_1m (ClickHouse)": ch.rows("SELECT count() n FROM agg_ohlcv_1m FINAL WHERE session_id=%(s)s", {"s": SID})[0]["n"]}
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM ingest_jobs WHERE batch_id LIKE 'sandbox-%'")
        c["ingest_jobs (PostgreSQL)"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM quarantine WHERE batch_id LIKE 'sandbox-%'")
        c["quarantine (PostgreSQL)"] = cur.fetchone()[0]
    c["сырьё sandbox-* (MinIO)"] = sum(1 for o in s3.list_objects(RAW_BUCKET, prefix="sandbox-", recursive=True)) if s3.bucket_exists(RAW_BUCKET) else 0
    return c


def status(ch):
    ensure(ch)
    r = ch.rows("SELECT status, start_at, end_at FROM ref_sessions FINAL WHERE session_id=%(s)s", {"s": SID})[0]
    return {"session_id": SID, "status": r["status"], "window": f"{DAY} 10:00–18:50"}


def check(ch, text):
    ensure(ch)
    raw = parse(text)
    verdicts, _ = classify_rows(ch, SOURCE, raw)
    return {"rows": verdict_rows(raw, verdicts), "summary": summary(verdicts)}


def send(ch, pg, s3, text, with_candles):
    ensure(ch)
    raw = parse(text)
    before = counts(ch, pg, s3)
    verdicts, _ = classify_rows(ch, SOURCE, raw)
    batch = f"sandbox-{int(time.time() * 1000)}"
    out = run_batch(pg, ch, s3, batch, SOURCE, raw)
    with pg.cursor() as cur:
        cur.execute("SELECT row_no, rule FROM quarantine WHERE batch_id=%s ORDER BY row_no", (batch,))
        quarantine = [{"row": r[0] + 1, "rule": r[1]} for r in cur.fetchall()]
    candles = None
    if with_candles:
        analytics.build_ohlcv(ch, SID)
        c = ch.rows("SELECT count() n, sum(volume) v, min(low) lo, max(high) hi, argMin(open, minute) o, argMax(close, minute) c "
                    "FROM agg_ohlcv_1m FINAL WHERE session_id=%(s)s", {"s": SID})[0]
        candles = c if c["n"] else {"n": 0}
    return {"batch": batch, "rows": verdict_rows(raw, verdicts), "summary": summary(verdicts), "quarantine": quarantine,
            "before": before, "after": counts(ch, pg, s3), "candles": candles, "batch_result": out}


def set_session(ch, new_status):
    ensure(ch)
    sessions.set_status(ch, SID, new_status)
    return status(ch)


def reset(ch):
    ensure(ch)
    ch.command("ALTER TABLE market_trades DELETE WHERE session_id = %(s)s SETTINGS mutations_sync = 1", {"s": SID})
    ch.command("ALTER TABLE agg_ohlcv_1m DELETE WHERE session_id = %(s)s SETTINGS mutations_sync = 1", {"s": SID})
    return set_session(ch, "open")
