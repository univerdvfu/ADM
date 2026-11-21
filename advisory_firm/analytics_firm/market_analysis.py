"""Интерактивная аналитика по минутным свечам и сделкам."""
import math
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

MIN_WINDOW = 15
MAX_WINDOW = 30
MAX_MATCHES = 5


def market_sessions(db, ticker_id=None):
    """Сессии, доступные обеим аналитическим функциям."""
    params = {"t": ticker_id}
    where = "WHERE a.ticker_id=%(t)s" if ticker_id is not None else ""
    rows = db.rows(f"""
        SELECT a.ticker_id AS ticker_id, a.session_id AS session_id, any(i.ticker) AS ticker,
               any(s.session_date) AS session_date, count() AS minutes,
               min(a.minute) AS first_minute, max(a.minute) AS last_minute
        FROM agg_ohlcv_1m AS a FINAL
        INNER JOIN ref_session_instruments AS i FINAL
            ON a.session_id=i.session_id AND a.ticker_id=i.ticker_id
        INNER JOIN ref_sessions AS s FINAL ON a.session_id=s.session_id
        {where}
        GROUP BY a.ticker_id, a.session_id
        ORDER BY session_date DESC, a.ticker_id, a.session_id DESC""", params)
    trades = {r["session_id"]: r["trades"] for r in db.rows(
        "SELECT session_id, count() AS trades FROM market_trades GROUP BY session_id")}
    for r in rows:
        r["trades"] = trades.get(r["session_id"], 0)
    return rows


def _parse_time(value, name):
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as e:
        raise ValueError(f"{name}: ожидается дата и время в формате ГГГГ-ММ-ДДTЧЧ:ММ") from e


def _features(window):
    base = float(window[0]["open"])
    volumes = [float(r["volume"]) for r in window]
    typical = max(median(volumes), 1.0)
    return {
        "price": [float(r["close"]) / base - 1 for r in window],
        "volume": [math.log1p(v / typical) for v in volumes],
        "range": [(float(r["high"]) - float(r["low"])) / base for r in window],
    }


def _rmse(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / len(a))


def _similarity(target, candidate):
    a, b = _features(target), _features(candidate)
    price = _rmse(a["price"], b["price"])
    volume = _rmse(a["volume"], b["volume"])
    volatility = _rmse(a["range"], b["range"])
    distance = math.sqrt(0.60 * (price / 0.01) ** 2
                         + 0.25 * (volume / 0.50) ** 2
                         + 0.15 * (volatility / 0.005) ** 2)
    return {"score": round(100 / (1 + distance), 2), "distance": round(distance, 6),
            "price_rmse": round(price, 8), "volume_rmse": round(volume, 8),
            "volatility_rmse": round(volatility, 8)}


def _public_candle(r):
    return {"minute": r["minute"], "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["volume"]),
            "trade_count": int(r["trade_count"]), "turnover": float(r["turnover"])}


def _volume_ratio(rows, start, length):
    current = sum(int(r["volume"]) for r in rows[start:start + length])
    previous = sum(int(r["volume"]) for r in rows[max(0, start - length):start])
    return round(current / previous, 4) if previous else None


def find_twins(db, ticker_id, session_id, end=None, length=20, limit=MAX_MATCHES):
    """Похожие прошлые окна той же бумаги; пересечения с эталоном не допускаются."""
    length = int(length)
    limit = int(limit)
    if not MIN_WINDOW <= length <= MAX_WINDOW:
        raise ValueError(f"Длина участка должна быть от {MIN_WINDOW} до {MAX_WINDOW} минут")
    if not 1 <= limit <= 10:
        raise ValueError("Количество аналогов должно быть от 1 до 10")
    end = _parse_time(end, "end")
    if end is None:
        found = db.rows("SELECT max(minute) AS end FROM agg_ohlcv_1m FINAL "
                        "WHERE ticker_id=%(t)s AND session_id=%(s)s",
                        {"t": ticker_id, "s": session_id})[0]["end"]
        if found is None:
            raise ValueError("В выбранной сессии нет минутных свечей")
        end = found.replace(tzinfo=None)
    target = list(reversed(db.rows("""
        SELECT * FROM agg_ohlcv_1m FINAL
        WHERE ticker_id=%(t)s AND session_id=%(s)s AND minute<=%(end)s
        ORDER BY minute DESC LIMIT %(n)s""",
        {"t": ticker_id, "s": session_id, "end": end, "n": length})))
    if len(target) < length:
        raise ValueError(f"До выбранного момента есть только {len(target)} свечей, нужно {length}")
    for row in target:
        row["minute"] = row["minute"].replace(tzinfo=None)
    if any((b["minute"] - a["minute"]).total_seconds() != 60 for a, b in zip(target, target[1:])):
        raise ValueError("В выбранном участке есть пропущенные минуты; нужен непрерывный интервал")

    all_rows = db.rows("SELECT * FROM agg_ohlcv_1m FINAL WHERE ticker_id=%(t)s ORDER BY minute",
                       {"t": ticker_id})
    sessions = {}
    for row in all_rows:
        row["minute"] = row["minute"].replace(tzinfo=None)
        sessions.setdefault(row["session_id"], []).append(row)
    target_start, target_end = target[0]["minute"], target[-1]["minute"]
    candidates = []
    for sid, rows in sessions.items():
        for start in range(0, len(rows) - length + 1):
            window = rows[start:start + length]
            if any((b["minute"] - a["minute"]).total_seconds() != 60 for a, b in zip(window, window[1:])):
                continue
            start_at, end_at = window[0]["minute"], window[-1]["minute"]
            if end_at >= target_start:
                continue
            future = rows[start + length:start + length + 30]
            outcomes = {}
            for horizon in (5, 15, 30):
                if len(future) >= horizon:
                    outcomes[str(horizon)] = round(
                        float(future[horizon - 1]["close"]) / float(window[-1]["close"]) - 1, 8)
            candidates.append({
                "session_id": sid, "start": start_at, "end": end_at,
                "return": round(float(window[-1]["close"]) / float(window[0]["open"]) - 1, 8),
                "volume_ratio": _volume_ratio(rows, start, length),
                "outcomes": outcomes,
                "candles": [_public_candle(r) for r in window + future],
                **_similarity(target, window),
            })
    candidates.sort(key=lambda r: (r["distance"], r["start"]))
    matches = []
    for candidate in candidates:
        if any(candidate["start"] <= m["end"] and candidate["end"] >= m["start"] for m in matches):
            continue
        matches.append(candidate)
        if len(matches) == limit:
            break
    target_rows = sessions[session_id]
    target_pos = next(i for i, r in enumerate(target_rows) if r["minute"] == target_start)
    return {
        "ticker_id": int(ticker_id), "session_id": int(session_id), "length": length,
        "target": {"start": target_start, "end": target_end,
                   "return": round(float(target[-1]["close"]) / float(target[0]["open"]) - 1, 8),
                   "volume_ratio": _volume_ratio(target_rows, target_pos, length),
                   "candles": [_public_candle(r) for r in target]},
        "matches": matches,
        "method": "60% траектория цены, 25% относительный объём, 15% диапазон свечей; RMSE, без нейросети",
        "disclaimer": "Исторические аналоги для исследования рынка, а не прогноз будущей доходности.",
    }


def butterfly_effect(db, ticker_id, session_id, start=None, end=None, top_percent=1):
    """Вклад заданной доли крупнейших по обороту сделок в VWAP и оборот."""
    start, end = _parse_time(start, "start"), _parse_time(end, "end")
    top_percent = float(top_percent)
    if not 0 < top_percent <= 50:
        raise ValueError("Доля крупнейших сделок должна быть больше 0 и не больше 50%")
    if start and end and start > end:
        raise ValueError("Начало интервала не может быть позже конца")
    conditions = ["ticker_id=%(t)s", "session_id=%(s)s"]
    if start:
        conditions.append("event_time>=%(start)s")
    if end:
        conditions.append("event_time<=%(end)s")
    rows = db.rows(f"""
        SELECT event_id, event_time, price, quantity, turnover,
               row_number() OVER (ORDER BY turnover DESC, event_time, event_id) AS rn
        FROM (
            SELECT event_id, event_time, price, quantity,
                   CAST(toDecimal128(price, 8) * quantity AS Decimal(30, 8)) AS turnover
            FROM market_trades WHERE {' AND '.join(conditions)}
        )""", {"t": ticker_id, "s": session_id, "start": start, "end": end})
    if not rows:
        raise ValueError("В выбранном интервале нет сделок")
    total_qty = sum(int(r["quantity"]) for r in rows)
    total_turnover = sum((Decimal(r["turnover"]) for r in rows), Decimal(0))
    top_n = max(1, math.ceil(len(rows) * top_percent / 100))
    top = rows[:top_n]
    rest = rows[top_n:]
    top_qty = sum(int(r["quantity"]) for r in top)
    top_turnover = sum((Decimal(r["turnover"]) for r in top), Decimal(0))
    rest_qty = total_qty - top_qty
    rest_turnover = total_turnover - top_turnover
    vwap = total_turnover / total_qty
    without = rest_turnover / rest_qty if rest_qty else None
    return {
        "ticker_id": int(ticker_id), "session_id": int(session_id),
        "start": min(r["event_time"] for r in rows).replace(tzinfo=None),
        "end": max(r["event_time"] for r in rows).replace(tzinfo=None),
        "trade_count": len(rows), "top_percent": top_percent, "top_count": top_n,
        "vwap": float(vwap), "without_top_vwap": float(without) if without is not None else None,
        "difference": float(vwap - without) if without is not None else None,
        "difference_pct": float((vwap / without - 1) * 100) if without else None,
        "turnover": float(total_turnover), "top_turnover": float(top_turnover),
        "top_turnover_share_pct": float(top_turnover / total_turnover * 100),
        "top_quantity_share_pct": float(Decimal(top_qty) / total_qty * 100),
        "top_trades": [{"event_id": r["event_id"], "event_time": r["event_time"],
                        "price": float(r["price"]), "quantity": int(r["quantity"]),
                        "turnover": float(r["turnover"])} for r in top[:30]],
        "disclaimer": "Показан вклад сделок в рассчитанную статистику, а не модель рынка без этих сделок.",
    }
