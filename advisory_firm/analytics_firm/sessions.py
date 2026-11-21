"""Жизненный цикл торговой сессии: открыта -> закрыта -> расчёты."""
from datetime import datetime

from . import analytics
from .reference import SESSION_COLS


def set_status(db, session_id, status):
    """ReplacingMergeTree без версии оставляет последнюю вставленную строку (читаем FINAL)."""
    r = db.rows("SELECT * FROM ref_sessions FINAL WHERE session_id=%(s)s", {"s": session_id})
    if not r:
        raise KeyError(session_id)
    r = r[0]
    db.insert("ref_sessions", SESSION_COLS,
              [[r["session_id"], r["session_date"], r["start_at"], r["end_at"], r["venue"], status]])


def close_session(db, session_id):
    """Закрытие: фиксируем статус, затем считаем свечи и сигналы по сессии."""
    set_status(db, session_id, "closed")
    analytics.build_ohlcv(db, session_id)
    return analytics.compute_signals(db, session_id)
