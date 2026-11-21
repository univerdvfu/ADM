"""Справочники: сессии и допуски инструментов к сессии."""
from datetime import date, datetime

from .contract import FORBIDDEN_FIELDS, Reject, to_decimal_20_8, to_uint

INSTRUMENT_TYPES = {"stock", "future", "option"}
CONTRACT_TERMS = {"fixed", "perpetual"}
EXERCISE_STYLES = {"american", "european"}


def pad_currency(code):
    """currency: поле шириной 4 знака (FixedString(4))."""
    code = str(code or "").strip().upper()
    if not code or len(code) > 4 or not code.isalpha():
        raise Reject("bad_currency")
    return code.ljust(4)


def validate_instrument(raw):
    if set(raw) & FORBIDDEN_FIELDS:
        raise Reject("forbidden_field")
    itype = raw.get("instrument_type")
    if itype not in INSTRUMENT_TYPES:
        raise Reject("bad_instrument_type")
    term = raw.get("contract_term") or ""
    style = raw.get("exercise_style") or ""
    maturity = raw.get("maturity_date")
    if isinstance(maturity, str):
        maturity = date.fromisoformat(maturity)
    # срок и стиль исполнения — независимые признаки
    if itype == "stock" and (term or style or maturity):
        raise Reject("derivative_attr_on_stock")
    if itype == "future":
        if term not in CONTRACT_TERMS or style:
            raise Reject("bad_future_attrs")
        if term == "fixed" and maturity is None:
            raise Reject("maturity_required")
        if term == "perpetual" and maturity is not None:
            raise Reject("maturity_forbidden")
    if itype == "option":
        if style not in EXERCISE_STYLES or term:
            raise Reject("bad_option_attrs")
    return {
        "session_id": to_uint(raw["session_id"], "bad_session_id"),
        "ticker_id": to_uint(raw["ticker_id"], "bad_ticker_id"),
        "instrument_id": to_uint(raw["instrument_id"], "bad_instrument_id"),
        "ticker": str(raw["ticker"]).strip(),
        "instrument_type": itype,
        "nominal_value": to_decimal_20_8(raw["nominal_value"], "bad_nominal"),
        "currency": pad_currency(raw.get("currency")),
        "contract_term": term,
        "exercise_style": style,
        "maturity_date": maturity,
        "lot_size": to_uint(raw["lot_size"], "bad_lot_size"),
        "tick_size": to_decimal_20_8(raw["tick_size"], "bad_tick_size"),
        "trading_status": str(raw.get("trading_status", "open")),
    }


INSTR_COLS = ["session_id", "ticker_id", "instrument_id", "ticker", "instrument_type",
              "nominal_value", "currency", "contract_term", "exercise_style",
              "maturity_date", "lot_size", "tick_size", "trading_status"]
SESSION_COLS = ["session_id", "session_date", "start_at", "end_at", "venue", "status"]


def load_reference(db, sessions, instruments):
    """Загружает сессии, затем допуски; допуск без известной сессии отклоняется."""
    s_rows = []
    for s in sessions:
        d = s["session_date"]
        d = date.fromisoformat(d) if isinstance(d, str) else d
        s_rows.append([to_uint(s["session_id"]), d, _dt(s["start_at"]), _dt(s["end_at"]),
                       s["venue"], s.get("status", "open")])
    db.insert("ref_sessions", SESSION_COLS, s_rows)
    known = {r[0] for r in s_rows} | {r["session_id"] for r in db.rows(
        "SELECT DISTINCT session_id FROM ref_sessions")}
    ok, rejected = [], []
    for i, raw in enumerate(instruments):
        try:
            rec = validate_instrument(raw)
            if rec["session_id"] not in known:
                raise Reject("unknown_session")
            ok.append([rec[c] for c in INSTR_COLS])
        except Reject as e:
            rejected.append((i, e.rule))
    db.insert("ref_session_instruments", INSTR_COLS, ok)
    return {"instruments": len(ok), "rejected": rejected}


def _dt(v):
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


def admitted_pairs(db):
    return {(r["session_id"], r["ticker_id"]) for r in db.rows(
        "SELECT session_id, ticker_id FROM ref_session_instruments FINAL "
        "WHERE trading_status != 'closed'")}
