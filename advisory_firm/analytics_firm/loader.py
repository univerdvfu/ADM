"""Загрузчик (H3-H5): проверка контракта, допуска ticker_id к session_id,
дедупликация по source_id + event_id, идемпотентность по batch_id."""
from datetime import datetime

from .contract import BAR_FIELDS, Reject, TRADE_FIELDS, validate_bar, validate_trade
from .reference import admitted_pairs


def _batch_seen(db, batch_id):
    return db.rows("SELECT count() AS n FROM ingest_batches WHERE batch_id=%(b)s",
                   {"b": batch_id})[0]["n"] > 0


def _existing_ids(db, source_id, event_ids):
    if not event_ids:
        return set()
    return {r["event_id"] for r in db.rows(
        "SELECT DISTINCT event_id FROM market_trades "
        "WHERE source_id=%(s)s AND event_id IN %(ids)s",
        {"s": source_id, "ids": tuple(event_ids)})}


def session_windows(db):
    """{session_id: (start_at, end_at, status)} по последней версии строки сессии."""
    return {r["session_id"]: (r["start_at"].replace(tzinfo=None), r["end_at"].replace(tzinfo=None),
                              r["status"]) for r in db.rows(
        "SELECT session_id, start_at, end_at, status FROM ref_sessions FINAL")}


def classify_rows(db, source_id, raw_rows):
    """Разбор пакета без записи: для каждой строки вердикт accepted / duplicate / rejected и правило.
    Возвращает (вердикты, принятые записи)."""
    pairs = admitted_pairs(db)
    windows = session_windows(db)
    verdicts, good = [], []
    for n, raw in enumerate(raw_rows):
        try:
            if not isinstance(raw, dict):
                raise Reject("bad_record")
            rec = validate_trade(raw)
            if rec["source_id"] != source_id:
                raise Reject("foreign_source")
            if (rec["session_id"], rec["ticker_id"]) not in pairs:
                raise Reject("ticker_not_admitted_to_session")
            if rec["session_id"] not in windows:
                raise Reject("unknown_session")
            start, end, status = windows[rec["session_id"]]
            if status == "closed":
                raise Reject("session_closed")               # после закрытия новые сделки не принимаются
            if not start <= rec["event_time"] <= end:
                raise Reject("outside_session_hours")        # до открытия или после окончания торгов
            good.append((n, rec))
        except Reject as e:
            verdicts.append({"n": n, "verdict": "rejected", "rule": e.rule})
    seen = _existing_ids(db, source_id, [r["event_id"] for _, r in good])
    fresh = []
    for n, rec in good:
        if rec["event_id"] in seen:
            verdicts.append({"n": n, "verdict": "duplicate", "rule": None})
        else:
            seen.add(rec["event_id"])
            fresh.append(rec)
            verdicts.append({"n": n, "verdict": "accepted", "rule": None})
    verdicts.sort(key=lambda v: v["n"])
    return verdicts, fresh


def ingest_trades(db, batch_id, source_id, raw_rows):
    if _batch_seen(db, batch_id):
        return {"skipped_batch": True, "accepted": 0, "duplicates": 0, "rejected": 0}
    verdicts, fresh = classify_rows(db, source_id, raw_rows)
    rejects = [(v["n"], v["rule"]) for v in verdicts if v["verdict"] == "rejected"]
    dups = sum(1 for v in verdicts if v["verdict"] == "duplicate")
    db.insert("market_trades", list(TRADE_FIELDS),
              [[r[c] for c in TRADE_FIELDS] for r in fresh])
    now = datetime.utcnow()
    # в журнал пишется только код правила, не копия полей записи
    db.insert("ingest_rejects", ["batch_id", "row_no", "rule", "logged_at"],
              [[batch_id, n, rule, now] for n, rule in rejects])
    db.insert("ingest_batches",
              ["batch_id", "source_id", "accepted", "duplicates", "rejected", "loaded_at"],
              [[batch_id, source_id, len(fresh), dups, len(rejects), now]])
    return {"skipped_batch": False, "accepted": len(fresh), "duplicates": dups,
            "rejected": len(rejects), "reject_rules": [r for _, r in rejects]}


def classify_bars(db, source_id, raw_bars):
    """Разбор дневных баров без записи: вердикт и правило по каждой строке."""
    pairs = admitted_pairs(db)
    verdicts, fresh, seen = [], [], set()
    for n, raw in enumerate(raw_bars):
        try:
            if not isinstance(raw, dict):
                raise Reject("bad_record")
            rec = validate_bar(raw)
            if rec["source_id"] != source_id:
                raise Reject("foreign_source")
            if (rec["session_id"], rec["ticker_id"]) not in pairs:
                raise Reject("ticker_not_admitted_to_session")
        except Reject as e:
            verdicts.append({"n": n, "verdict": "rejected", "rule": e.rule})
            continue
        key = (rec["ticker_id"], rec["session_id"])
        if key in seen:
            verdicts.append({"n": n, "verdict": "duplicate", "rule": None})
        else:
            seen.add(key)
            fresh.append(rec)
            verdicts.append({"n": n, "verdict": "accepted", "rule": None})
    return verdicts, fresh


def ingest_bars(db, batch_id, source_id, raw_bars):
    """Бракованный бар в daily_bars не попадает: в журнал идёт только код правила.
    Повторный бар по тому же (бумага, сессия) заменяет прежний (ReplacingMergeTree)."""
    if _batch_seen(db, batch_id):
        return {"skipped_batch": True, "accepted": 0, "duplicates": 0, "rejected": 0, "reject_rules": []}
    verdicts, fresh = classify_bars(db, source_id, raw_bars)
    rejects = [(v["n"], v["rule"]) for v in verdicts if v["verdict"] == "rejected"]
    dups = sum(1 for v in verdicts if v["verdict"] == "duplicate")
    now = datetime.utcnow()
    db.insert("daily_bars", list(BAR_FIELDS) + ["loaded_at"], [[r[c] for c in BAR_FIELDS] + [now] for r in fresh])
    db.insert("ingest_rejects", ["batch_id", "row_no", "rule", "logged_at"],
              [[batch_id, n, rule, now] for n, rule in rejects])
    db.insert("ingest_batches",
              ["batch_id", "source_id", "accepted", "duplicates", "rejected", "loaded_at"],
              [[batch_id, source_id, len(fresh), dups, len(rejects), now]])
    return {"skipped_batch": False, "accepted": len(fresh), "duplicates": dups,
            "rejected": len(rejects), "reject_rules": [r for _, r in rejects]}
