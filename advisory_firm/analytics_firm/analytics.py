"""Расчёты H7-H8: свечи OHLCV по ticker_id + session_id + minute, сигналы."""
from datetime import datetime
from decimal import Decimal

METHOD_VERSION = "rules-v1"
MIN_TRADES = 5          # меньше — недостаточно данных
UP_THRESHOLD = 0.01     # доходность за сессию


def build_ohlcv(db, session_id=None):
    """Пересчёт свечей; open/close — по времени и event_id, не по порядку поступления.
    Повторный запуск безопасен: ReplacingMergeTree оставляет последнюю версию."""
    where = "WHERE session_id = %(s)s" if session_id is not None else ""
    db.command(f"""
        INSERT INTO agg_ohlcv_1m
        SELECT ticker_id, session_id, toStartOfMinute(event_time) AS minute,
               argMin(price, (event_time, event_id)),
               max(price), min(price),
               argMax(price, (event_time, event_id)),
               sum(quantity), count(),
               CAST(sum(toDecimal128(price, 8) * quantity) AS Decimal(30, 8)),
               now64(3)
        FROM market_trades {where}
        GROUP BY ticker_id, session_id, minute""", {"s": session_id})


def compute_signals(db, session_id=None):
    where = "WHERE session_id = %(s)s" if session_id is not None else ""
    rows = db.rows(f"""
        SELECT ticker_id, session_id,
               argMin(open, minute) AS first_open, argMax(close, minute) AS last_close,
               sum(volume) AS volume, sum(trade_count) AS trades, sum(turnover) AS turnover
        FROM agg_ohlcv_1m FINAL {where}
        GROUP BY ticker_id, session_id""", {"s": session_id})
    out, now = [], datetime.utcnow()
    for r in rows:
        ret = float((r["last_close"] - r["first_open"]) / r["first_open"])
        if r["trades"] < MIN_TRADES:
            sig = "insufficient_data"
        elif ret >= UP_THRESHOLD:
            sig = "up"
        elif ret <= -UP_THRESHOLD:
            sig = "down"
        else:
            sig = "flat"
        out.append([r["ticker_id"], r["session_id"], METHOD_VERSION, sig,
                    ret, ret, Decimal(r["turnover"]), r["trades"], now])
    db.insert("signals", ["ticker_id", "session_id", "method_version", "signal",
                          "score", "ret", "turnover", "trade_count", "as_of"], out)
    return out


def get_signal(db, ticker_id, session_id):
    rows = db.rows("""SELECT * FROM signals FINAL
                      WHERE ticker_id=%(t)s AND session_id=%(s)s
                        AND method_version=%(m)s""",
                   {"t": ticker_id, "s": session_id, "m": METHOD_VERSION})
    return rows[0] if rows else None
