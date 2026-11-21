"""Источник реальных данных: публичный API Мосбиржи (ISS). Только разрешённые поля."""
import json
import urllib.request
from datetime import datetime

BASE = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/{board}"
SOURCE_ID = "MOEX-ISS"


def _get(url):
    with urllib.request.urlopen(url + ("&" if "?" in url else "?") + "iss.meta=off",
                                timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_trades(secid, board="TQBR", date=None, limit=5000):
    q = f"?limit={limit}" + (f"&date={date}" if date else "")
    return _get(BASE.format(board=board) + f"/securities/{secid}/trades.json{q}")


def fetch_security(secid, board="TQBR"):
    return _get(BASE.format(board=board) + f"/securities/{secid}.json?iss.only=securities")


def _table(payload, name):
    t = payload[name]
    return [dict(zip(t["columns"], row)) for row in t["data"]]


def session_id_for(day):
    """session_id = YYYYMMDD торгового дня."""
    return int(str(day).replace("-", ""))


def parse_trades(payload, ticker_id):
    """Только рыночные атрибуты. Покупатель/продавец (BUYSELL) — не переносим."""
    rows = []
    for t in _table(payload, "trades"):
        rows.append({
            "source_id": SOURCE_ID,
            "event_id": str(t["TRADENO"]),
            "ticker_id": ticker_id,
            "session_id": session_id_for(t["TRADEDATE"]),
            "event_time": datetime.fromisoformat(f"{t['TRADEDATE']}T{t['TRADETIME']}"),
            "price": t["PRICE"],
            "quantity": t["QUANTITY"],
        })
    return rows


def parse_instrument(payload, ticker_id, instrument_id, day):
    sec = next(s for s in _table(payload, "securities") if s["BOARDID"])
    return {
        "session_id": session_id_for(day), "ticker_id": ticker_id,
        "instrument_id": instrument_id, "ticker": sec["SECID"],
        "instrument_type": "stock",
        "nominal_value": sec["FACEVALUE"], "currency": sec["FACEUNIT"] or "RUB",
        "lot_size": sec["LOTSIZE"], "tick_size": sec["MINSTEP"],
        "trading_status": "open" if sec["STATUS"] == "A" else "closed",
    }


def parse_session(day, board="TQBR", status="open"):
    return {"session_id": session_id_for(day), "session_date": str(day),
            "start_at": f"{day}T10:00:00", "end_at": f"{day}T18:50:00",
            "venue": f"MOEX/{board}", "status": status}
