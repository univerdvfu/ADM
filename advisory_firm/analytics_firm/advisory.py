"""Инвестиционное консультирование: данные Мосбиржи -> показатели -> рекомендации клиентам.
Клиенты, портфели и журнал рекомендаций — в PostgreSQL; рыночные ряды — в ClickHouse."""
import json
import math
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from . import moex
from .reference import pad_currency

METHOD_VERSION = "advisory-v1"
MOM_THRESHOLD = 0.03                # |доходность| за окно для buy/sell
LOOKBACK = 20
RISK_ALLOWED = {"conservative": {"low"}, "moderate": {"low", "medium"},
                "aggressive": {"low", "medium", "high"}}
DISCLOSURE = ("Рекомендация носит информационный характер, не гарантирует доходность; "
              "цены могут снижаться, возможна потеря части вложений.")


# ---------- загрузка данных Мосбиржи ----------

def parse_history(payload, ticker_id):
    t = payload["history"]
    out = []
    for row in t["data"]:
        r = dict(zip(t["columns"], row))
        if r["OPEN"] is None or r["CLOSE"] is None:
            continue                                        # день без торгов
        out.append({"source_id": moex.SOURCE_ID, "ticker_id": ticker_id,
                    "session_id": moex.session_id_for(r["TRADEDATE"]),
                    "trade_date": date.fromisoformat(r["TRADEDATE"]),
                    "open": Decimal(str(r["OPEN"])), "high": Decimal(str(r["HIGH"])),
                    "low": Decimal(str(r["LOW"])), "close": Decimal(str(r["CLOSE"])),
                    "volume": int(r["VOLUME"]), "turnover": Decimal(str(r["VALUE"])),
                    "num_trades": int(r["NUMTRADES"])})
    return out


BAR_COLS = ["source_id", "ticker_id", "session_id", "trade_date", "open", "high", "low",
            "close", "volume", "turnover", "num_trades"]


def load_bars(ch, bars):
    """Идемпотентно: ключ (ticker_id, session_id) схлопывает ReplacingMergeTree."""
    now = datetime.utcnow()
    ch.insert("daily_bars", BAR_COLS + ["loaded_at"],
              [[b[c] for c in BAR_COLS] + [now] for b in bars])
    return len(bars)


def seed_from_moex(pg, ch, fixtures_dir, tickers, report=None):
    """tickers: список SECID. Заполняет справочники PG, бары CH; возвращает {secid: ticker_id}."""
    fixtures_dir = Path(fixtures_dir)
    ids, all_bars, days = {}, [], set()
    with pg.cursor() as cur:
        for n, secid in enumerate(tickers, start=1):
            sec = json.loads((fixtures_dir / f"sec_{secid}.json").read_text(encoding="utf-8"))
            hist = json.loads((fixtures_dir / f"hist_{secid}.json").read_text(encoding="utf-8"))
            row = dict(zip(sec["securities"]["columns"], sec["securities"]["data"][0]))
            cur.execute("INSERT INTO issuers VALUES (%s,%s,'RU') ON CONFLICT DO NOTHING",
                        (n, row["SHORTNAME"]))
            cur.execute("INSERT INTO instruments VALUES (%s,%s,'stock',%s,%s,NULL,NULL,NULL) "
                        "ON CONFLICT DO NOTHING",
                        (n, n, Decimal(str(row["FACEVALUE"])), pad_currency(row["FACEUNIT"])))
            cur.execute("INSERT INTO tickers VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (n, n, secid))
            bars = parse_history(hist, n)
            all_bars += bars
            days |= {(b["session_id"], b["trade_date"]) for b in bars}
            ids[secid] = (n, Decimal(str(row["LOTSIZE"])), Decimal(str(row["MINSTEP"])))
        for sid, d in sorted(days):
            cur.execute("""INSERT INTO trading_sessions VALUES (%s,%s,%s,%s,'MOEX/TQBR','closed')
                           ON CONFLICT DO NOTHING""",
                        (sid, d, f"{d} 10:00+03", f"{d} 18:50+03"))
        by_id = {v[0]: v for v in ids.values()}
        for b in all_bars:
            n, lot, step = by_id[b["ticker_id"]]
            cur.execute("INSERT INTO session_instruments VALUES (%s,%s,'open',%s,%s) "
                        "ON CONFLICT DO NOTHING", (b["session_id"], n, lot, step))
    pg.commit()
    from .stack import export_reference, run_bars_batch
    export_reference(pg, ch)
    out = run_bars_batch(pg, ch, f"bars-{int(time.time() * 1000)}", moex.SOURCE_ID,
                         f"moex/{Path(fixtures_dir).name}", all_bars)
    if report is not None:
        report.update(out)
    return {s: v[0] for s, v in ids.items()}


# ---------- показатели ----------

def series(ch, pg, ticker_id, asof=None):
    """Закрытия с поправкой на сплиты (по корпоративным событиям из PostgreSQL)."""
    rows = ch.rows("""SELECT trade_date, close FROM daily_bars FINAL
                      WHERE ticker_id=%(t)s AND trade_date <= %(a)s ORDER BY trade_date""",
                   {"t": ticker_id, "a": asof or date(2100, 1, 1)})
    with pg.cursor() as cur:
        cur.execute("SELECT ex_date, split_ratio FROM corporate_events "
                    "WHERE ticker_id=%s AND event_type='split'", (ticker_id,))
        splits = cur.fetchall()
        cur.execute("SELECT ex_date, amount FROM corporate_events "
                    "WHERE ticker_id=%s AND event_type='dividend'", (ticker_id,))
        divs = cur.fetchall()
    out = []
    for r in rows:
        adj = r["close"]
        for ex, ratio in splits:
            if r["trade_date"] < ex:
                adj = adj / ratio
        out.append((r["trade_date"], adj))
    return out, list(divs)


def metrics(ch, pg, ticker_id, asof=None, lookback=LOOKBACK):
    s, divs = series(ch, pg, ticker_id, asof)
    if len(s) < lookback + 1:
        return None
    w = s[-(lookback + 1):]
    closes = [float(c) for _, c in w]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    mean = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(252)
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = max(mdd, 1 - c / peak)
    div_sum = sum(float(a) for d, a in divs if w[0][0] < d <= w[-1][0])
    return {"ret": (closes[-1] + div_sum) / closes[0] - 1, "vol": vol, "max_drawdown": mdd,
            "last_close": Decimal(w[-1][1]), "cutoff": w[-1][0]}


def risk_class(vol):
    return "low" if vol < 0.25 else "medium" if vol < 0.45 else "high"


# ---------- рекомендации ----------

def advise(pg, ch, client_id, ticker_id, author, asof=None):
    m = metrics(ch, pg, ticker_id, asof)
    if m is None:
        raise ValueError("not enough history")
    with pg.cursor() as cur:
        cur.execute("SELECT risk_profile, max_position_pct FROM advisory_clients "
                    "WHERE client_id=%s", (client_id,))
        profile, max_pct = cur.fetchone()
        cur.execute("SELECT ticker_id, quantity FROM positions WHERE client_id=%s", (client_id,))
        holdings = cur.fetchall()
    rc = risk_class(m["vol"])
    action = "buy" if m["ret"] >= MOM_THRESHOLD else "sell" if m["ret"] <= -MOM_THRESHOLD else "hold"
    notes = [f"доходность {LOOKBACK} сессий {m['ret']:+.2%}", f"волатильность {m['vol']:.1%}",
             f"класс риска {rc}"]
    if action == "buy" and rc not in RISK_ALLOWED[profile]:
        action = "hold"
        notes.append(f"не подходит профилю {profile}")
    if action == "buy":
        values = {}
        for tid, qty in holdings:
            sr, _ = series(ch, pg, tid, asof)
            values[tid] = float(sr[-1][1]) * qty if sr else 0.0
        total = sum(values.values())
        if total and values.get(ticker_id, 0) / total * 100 >= float(max_pct):
            action = "hold"
            notes.append(f"доля позиции достигла лимита {max_pct}%")
    rec_id = uuid.uuid4()
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO recommendations (rec_id, client_id, ticker_id, action,
                       risk_class, method_version, data_cutoff, rationale, risk_disclosure, author)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (str(rec_id), client_id, ticker_id, action, rc, METHOD_VERSION,
                     m["cutoff"], "; ".join(notes), DISCLOSURE, author))
        cur.execute("INSERT INTO recommendation_status_events (rec_id,status,actor) "
                    "VALUES (%s,'draft',%s)", (str(rec_id), author))
    pg.commit()
    return str(rec_id)


def _status(pg, rec_id):
    with pg.cursor() as cur:
        cur.execute("SELECT status FROM recommendation_status_events WHERE rec_id=%s "
                    "ORDER BY event_id DESC LIMIT 1", (rec_id,))
        return cur.fetchone()[0]


def _set(pg, rec_id, status, actor):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO recommendation_status_events (rec_id,status,actor) "
                    "VALUES (%s,%s,%s)", (rec_id, status, actor))
    pg.commit()


def review(pg, rec_id, reviewer, approve):
    with pg.cursor() as cur:
        cur.execute("SELECT author FROM recommendations WHERE rec_id=%s", (rec_id,))
        author = cur.fetchone()[0]
    if reviewer == author:
        raise PermissionError("author cannot review own recommendation")
    if _status(pg, rec_id) != "draft":
        raise ValueError("only drafts can be reviewed")
    _set(pg, rec_id, "approved" if approve else "rejected", reviewer)


def publish(pg, rec_id, actor):
    if _status(pg, rec_id) != "approved":
        raise ValueError("only approved recommendations can be published")
    _set(pg, rec_id, "published", actor)


def client_report(pg, client_id):
    """Клиенту: только опубликованное; без внутренних ID и авторов."""
    with pg.cursor() as cur:
        cur.execute("""SELECT c.alias, t.ticker, r.action, r.risk_class, r.rationale,
                              r.risk_disclosure, r.data_cutoff
                       FROM recommendations r
                       JOIN advisory_clients c USING (client_id) JOIN tickers t USING (ticker_id)
                       WHERE r.client_id=%s AND (SELECT status FROM recommendation_status_events e
                             WHERE e.rec_id=r.rec_id ORDER BY event_id DESC LIMIT 1)='published'
                       ORDER BY r.created_at""", (client_id,))
        cols = ("alias", "ticker", "action", "risk_class", "rationale", "risk_disclosure",
                "data_cutoff")
        return [dict(zip(cols, r)) for r in cur.fetchall()]
