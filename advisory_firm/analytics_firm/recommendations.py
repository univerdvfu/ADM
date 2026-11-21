"""Рекомендации (H9-H12), роли и аудит (уровни 4-5)."""
import uuid
from datetime import datetime

from .analytics import METHOD_VERSION, get_signal

ROLE_RIGHTS = {
    "data_engineer": {"ingest"},
    "analyst": {"read_facts", "draft"},
    "reviewer": {"read_facts", "review", "publish"},
    "security_admin": {"read_audit"},
    "customer": {"read_published"},
}
ACTION_BY_SIGNAL = {"up": "buy", "down": "sell", "flat": "hold"}
COLS = ["rec_id", "ticker_id", "session_id", "method_version", "action", "horizon",
        "rationale", "author", "reviewer", "review_status", "published_at", "version"]


class Denied(Exception):
    pass


def require(role, right):
    if right not in ROLE_RIGHTS.get(role, set()):
        raise Denied(f"{role} cannot {right}")


def audit(db, actor, role, action, obj):
    db.insert("audit_log", ["ts", "actor", "role", "action", "object"],
              [[datetime.utcnow(), actor, role, action, obj]])


def _save(db, rec):
    rec["version"] = datetime.utcnow()
    db.insert("recommendations", COLS, [[rec[c] for c in COLS]])


def _get(db, rec_id):
    rows = db.rows("SELECT * FROM recommendations FINAL WHERE rec_id=%(r)s", {"r": rec_id})
    if not rows:
        raise KeyError(rec_id)
    return dict(rows[0])


def draft(db, analyst, ticker_id, session_id, horizon="1d"):
    require("analyst", "draft")
    sig = get_signal(db, ticker_id, session_id)
    if sig is None or sig["signal"] == "insufficient_data":
        raise ValueError("no sufficient signal for recommendation")
    rec = {"rec_id": uuid.uuid4().hex, "ticker_id": ticker_id, "session_id": session_id,
           "method_version": METHOD_VERSION, "action": ACTION_BY_SIGNAL[sig["signal"]],
           "horizon": horizon, "author": analyst, "reviewer": "", "published_at": None,
           "review_status": "draft",
           "rationale": f"signal={sig['signal']}, return={sig['ret']:.4f}, "
                        f"trades={sig['trade_count']}"}
    _save(db, rec)
    audit(db, analyst, "analyst", "draft", rec["rec_id"])
    return rec["rec_id"]


def review(db, reviewer, rec_id, approve):
    require("reviewer", "review")
    rec = _get(db, rec_id)
    if rec["review_status"] != "draft":
        raise ValueError("only drafts can be reviewed")
    if reviewer == rec["author"]:
        raise Denied("author cannot review own recommendation")
    rec["reviewer"] = reviewer
    rec["review_status"] = "approved" if approve else "rejected"
    _save(db, rec)
    audit(db, reviewer, "reviewer", "review_" + rec["review_status"], rec_id)


def publish(db, reviewer, rec_id):
    require("reviewer", "publish")
    rec = _get(db, rec_id)
    if rec["review_status"] != "approved":
        raise ValueError("only approved recommendations can be published")
    rec["review_status"] = "published"
    rec["published_at"] = datetime.utcnow()
    _save(db, rec)
    audit(db, reviewer, "reviewer", "publish", rec_id)


def customer_report(db):
    """Единственный канал для заказчика: только опубликованные рекомендации."""
    require("customer", "read_published")
    return db.rows("""
        SELECT r.rec_id, i.ticker, r.action, r.horizon, r.rationale,
               r.method_version, r.published_at
        FROM (SELECT * FROM recommendations FINAL WHERE review_status='published') AS r
        LEFT JOIN (SELECT DISTINCT ticker_id, ticker FROM ref_session_instruments FINAL) AS i
          ON r.ticker_id = i.ticker_id
        ORDER BY r.published_at""")


def read_audit(db, role):
    require(role, "read_audit")
    return db.rows("SELECT * FROM audit_log ORDER BY ts")
