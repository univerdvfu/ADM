"""Демонстрация: как данные идут в БД, что происходит при открытии и закрытии биржи,
какие есть тесты и что получается в результате. Пишет demo/report.html.

Запуск (нужны запущенные сервисы):  bash deploy/demo.sh [--offline] [--skip-tests]
"""
import argparse
import html
import json
import math
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pgserver
import psycopg2

from analytics_firm import advisory, analytics, jobs, moex, sessions
from analytics_firm.db import Db
from analytics_firm.loader import ingest_trades
from analytics_firm.reference import load_reference
from analytics_firm.stack import RAW_BUCKET, create_pg_schema

OUT = Path(__file__).resolve().parent
TICKERS = jobs.DEFAULT_TICKERS
FIXTURES = ROOT / "tests" / "fixtures" / "moex"
SUITES = {
    "test_db_complex": "15 тестов на сложные задачи БД: агрегаты, транзакции, конкурентность, окна, ASOF JOIN, большой объём, партиции",
}


def log(msg):
    print(msg, flush=True)


def fixture_fetch(secid, start, end):
    load = lambda n: json.loads((FIXTURES / n).read_text(encoding="utf-8"))
    return load(f"hist_{secid}.json"), load(f"sec_{secid}.json")


def step_ingest(pg, ch, s3, offline):
    day = date.today()
    source = "сохранённые ответы биржи (офлайн)"
    fetch = fixture_fetch
    if not offline:
        try:
            moex.fetch_security("SBER")
            fetch, source = None, "живой API Мосбиржи (iss.moex.com)"
        except Exception as e:
            log(f"API недоступен ({e}), берём сохранённые ответы")
    keys = jobs.fetch_raw(s3, TICKERS, day, fetch=fetch)
    objs = [(o.object_name, o.size) for o in s3.list_objects(RAW_BUCKET, prefix=f"moex/{day}/", recursive=True)]
    ids = jobs.load_from_raw(pg, ch, s3, TICKERS, day, OUT / ".raw")
    quality = jobs.quality_check(ch)
    with pg.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")
        pg_counts = []
        for (t,) in cur.fetchall():
            cur.execute(f'SELECT count(*) FROM "{t}"')
            pg_counts.append((t, cur.fetchone()[0]))
    ch_counts = [(t, ch.rows(f"SELECT count() n FROM {t}")[0]["n"]) for t in sorted(ch.tables())]
    return dict(day=day, source=source, objs=objs, ids=ids, quality=quality,
                pg=pg_counts, ch=ch_counts)


def step_session(ch):
    """Один торговый день SBER: сделки до открытия, в часы торгов, закрытие, опоздавшая сделка."""
    bar = ch.rows("SELECT * FROM daily_bars FINAL WHERE ticker_id=1 ORDER BY trade_date DESC LIMIT 1")[0]
    d = bar["trade_date"]
    sid = 20990101
    load_reference(ch, [{"session_id": sid, "session_date": d, "start_at": f"{d}T10:00:00",
                         "end_at": f"{d}T18:50:00", "venue": "MOEX/TQBR (демо)", "status": "open"}],
                   [{"session_id": sid, "ticker_id": 1, "instrument_id": 1, "ticker": "SBER",
                     "instrument_type": "stock", "nominal_value": "3", "currency": "SUR",
                     "lot_size": 1, "tick_size": "0.01"}])
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    pts = [(10, 0, o), (12, 10, h), (15, 30, l), (18, 50, c)]            # ломаная по реальному бару
    rnd, trades, n = random.Random(7), [], 100
    for (h1, m1, p1), (h2, m2, p2) in zip(pts, pts[1:]):
        t1, t2 = h1 * 60 + m1, h2 * 60 + m2
        for t in range(t1, t2, 15):
            price = p1 + (p2 - p1) * (t - t1) / (t2 - t1)
            lo, hi = min(h, max(l, price + rnd.uniform(-0.1, 0.1))), None
            trades.append((n, datetime(d.year, d.month, d.day, t // 60, t % 60, 5), round(lo, 2))); n += 1
    trades.append((n, datetime(d.year, d.month, d.day, 18, 50, 0), c))
    mk = lambda i, when, price: {"source_id": "MOEX-ISS", "event_id": str(i), "ticker_id": 1,
                                 "session_id": sid, "event_time": when, "price": price, "quantity": 10}
    t0 = datetime(d.year, d.month, d.day)
    events = []
    probes = [("до открытия", mk(1, t0.replace(hour=9, minute=59, second=59), o))]
    for tag, row in probes:
        r = ingest_trades(ch, f"probe-{row['event_id']}", "MOEX-ISS", [row])
        events.append((row["event_time"], "Сделка " + tag, r))
    r = ingest_trades(ch, "session-main", "MOEX-ISS", [mk(i, w, p) for i, w, p in trades])
    events.append((t0.replace(hour=10), f"Торги идут: {len(trades)} сделок за день", r))
    r = ingest_trades(ch, "probe-late", "MOEX-ISS", [mk(2, t0.replace(hour=18, minute=50, second=1), c)])
    events.append((t0.replace(hour=18, minute=50, second=1), "Сделка через секунду после окончания", r))
    pre = ch.rows("SELECT count() n FROM agg_ohlcv_1m")[0]["n"]
    sig = sessions.close_session(ch, sid)
    events.append((t0.replace(hour=18, minute=50, second=30), "Сессия закрыта, расчёт свечей и сигнала",
                   {"accepted": 0, "rejected": 0, "reject_rules": [], "info": f"свечей до закрытия: {pre}"}))
    r = ingest_trades(ch, "probe-after-close", "MOEX-ISS", [mk(3, t0.replace(hour=18, minute=55), c)])
    events.append((t0.replace(hour=18, minute=55), "Сделка после закрытия сессии", r))
    candles = ch.rows("SELECT count() n, sum(trade_count) t, argMin(open, minute) o, argMax(close, minute) c "
                      "FROM agg_ohlcv_1m FINAL WHERE session_id=%(s)s", {"s": sid})[0]
    signal = analytics.get_signal(ch, 1, sid)
    return dict(date=d, events=events, candles=candles, signal=signal, bar=bar)


def step_results(pg, ch):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO advisory_clients VALUES (1,'client-A','conservative',365,30,'active'),"
                    "(2,'client-B','aggressive',90,100,'active') ON CONFLICT DO NOTHING")
    pg.commit()
    made = jobs.refresh_recommendations(pg, ch)
    with pg.cursor() as cur:
        cur.execute("SELECT rec_id::text FROM recommendations")
        rec_ids = [r[0] for r in cur.fetchall()]
    for rid in rec_ids:
        advisory.review(pg, rid, "boris", True)
        advisory.publish(pg, rid, "boris")
    reports = {cid: advisory.client_report(pg, cid) for cid in (1, 2)}
    with pg.cursor() as cur:
        cur.execute("SELECT ticker_id, ticker FROM tickers ORDER BY 1")
        names = dict(cur.fetchall())
    metrics = {names[t]: advisory.metrics(ch, pg, t) for t in names}
    series = {}
    for t, name in names.items():
        s, _ = advisory.series(ch, pg, t)
        series[name] = [(d, float(c)) for d, c in s]
    return dict(made=made, reports=reports, metrics=metrics, series=series)


def step_tests(skip):
    junit = OUT / "junit.xml"
    if not skip:
        log("Запуск тестов…")
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        f"--junitxml={junit}", str(ROOT / "tests" / "test_db_complex.py")], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not junit.exists():
        return None
    suites = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        mod = case.get("classname", "").split(".")[-1] or case.get("classname")
        status = "fail" if case.find("failure") is not None or case.find("error") is not None else \
                 "skip" if case.find("skipped") is not None else "ok"
        suites.setdefault(mod, []).append((case.get("name"), status))
    return suites


# ---------- HTML ----------

CSS = """
:root{--bg:#f4f6f9;--card:#fff;--ink:#1e293b;--muted:#5b6b7f;--navy:#10243e;--teal:#1f7a7a;--gold:#b97d12;
--line:#d5dce6;--ok:#17803d;--bad:#b42318;--soft:#e6eef5}
@media(prefers-color-scheme:dark){:root{--bg:#0e1726;--card:#16233a;--ink:#e2e8f0;--muted:#9fb0c5;--navy:#cfe0f5;
--teal:#4fc3c3;--gold:#f0b44c;--line:#2b4263;--ok:#4ade80;--bad:#f87171;--soft:#1c2d47}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 Calibri,Segoe UI,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 20px 64px}h1{font:700 34px/1.2 Cambria,Georgia,serif;color:var(--navy);margin:0 0 6px}
h2{font:700 24px Cambria,Georgia,serif;color:var(--navy);margin:44px 0 6px}p.lead{color:var(--muted);margin:0 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th{background:var(--navy);color:var(--bg);text-align:left;padding:8px 10px}
td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.stat{text-align:center}
.stat b{display:block;font:700 40px Cambria,Georgia,serif;color:var(--navy)}.stat span{color:var(--muted)}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}.skip{color:var(--gold);font-weight:600}
code{font-family:Consolas,monospace;font-size:13px}details{margin:6px 0}summary{cursor:pointer;font-weight:600}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:800px){.two{grid-template-columns:1fr}}
svg{width:100%;height:auto}.leg span{display:inline-block;margin-right:16px;font-size:14px}.leg i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px}
"""
E = html.escape
PALETTE = ["#1f7a7a", "#d99a2b", "#6b5bd2", "#c2410c", "#2563eb"]


def table(head, rows, num=()):
    th = "".join(f'<th class="{"n" if i in num else ""}">{E(h)}</th>' for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td class="{"n" if i in num else ""}">{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><tr>{th}</tr>{body}</table>"


def chart(series):
    W, H, L, B = 1000, 340, 50, 30
    allv = [v for s in series.values() for _, v in s]
    base = {k: s[0][1] for k, s in series.items()}
    norm = {k: [(d, v / base[k] * 100) for d, v in s] for k, s in series.items()}
    vals = [v for s in norm.values() for _, v in s]
    lo, hi = math.floor(min(vals) / 5) * 5, math.ceil(max(vals) / 5) * 5
    dates = sorted({d for s in norm.values() for d, _ in s})
    x = lambda d: L + (W - L - 10) * dates.index(d) / max(1, len(dates) - 1)
    y = lambda v: 10 + (H - B - 10) * (1 - (v - lo) / (hi - lo))
    g = "".join(f'<line x1="{L}" x2="{W-10}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--line)"/>'
                f'<text x="{L-6}" y="{y(v)+4:.1f}" text-anchor="end" font-size="12" fill="var(--muted)">{v}</text>'
                for v in range(lo, hi + 1, 5))
    xt = "".join(f'<text x="{x(dates[i]):.1f}" y="{H-8}" text-anchor="middle" font-size="12" fill="var(--muted)">{dates[i]:%d.%m}</text>'
                 for i in range(0, len(dates), max(1, len(dates) // 8)))
    lines = "".join(f'<polyline fill="none" stroke="{PALETTE[i % 5]}" stroke-width="2" points="' +
                    " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in s) + '"/>' for i, s in enumerate(norm.values()))
    leg = "".join(f'<span><i style="background:{PALETTE[i % 5]}"></i>{E(k)}</span>' for i, k in enumerate(norm))
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Цены закрытия, начало периода = 100">{g}{xt}{lines}</svg>'
            f'<div class="leg">{leg}</div>')


def render(ing, ses, res, suites):
    out = ['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>Демонстрация: данные Мосбиржи</title><style>{CSS}</style><main>"]
    out.append("<h1>Как данные Мосбиржи попадают в базы и что из них получается</h1>"
               f'<p class="lead">Запуск от {datetime.now():%d.%m.%Y %H:%M}. Источник: {E(ing["source"])}.</p>')

    # 1. данные -> БД
    q = ing["quality"]
    out.append("<h2>1. Откуда приходят данные и как ложатся в БД</h2>"
               '<p class="lead">API биржи → сырьё в MinIO → загрузка → PostgreSQL (справочники) и ClickHouse (ряды) → проверка качества.</p>'
               f'<div class="grid"><div class="card stat"><b>{len(ing["objs"])}</b><span>файлов сырья в MinIO</span></div>'
               f'<div class="card stat"><b>{q["tickers"]}</b><span>бумаг</span></div>'
               f'<div class="card stat"><b>{q["total"]}</b><span>дневных баров</span></div>'
               f'<div class="card stat"><b>{q["bad"]}</b><span>ошибок качества</span></div></div>')
    out.append('<div class="two"><div class="card"><b>PostgreSQL</b>' +
               table(["Таблица", "Строк"], [(f"<code>{E(t)}</code>", n) for t, n in ing["pg"]], num=(1,)) +
               '</div><div class="card"><b>ClickHouse</b>' +
               table(["Таблица", "Строк"], [(f"<code>{E(t)}</code>", n) for t, n in ing["ch"]], num=(1,)) + "</div></div>")
    out.append('<details class="card"><summary>Сырьё в MinIO (бакет raw-market)</summary>' +
               table(["Объект", "Байт"], [(f"<code>{E(n)}</code>", s) for n, s in ing["objs"]], num=(1,)) + "</details>")

    # 2. открытие и закрытие
    out.append(f"<h2>2. Открытие и закрытие биржи</h2>"
               f'<p class="lead">Демонстрационная сессия SBER за {ses["date"]:%d.%m.%Y}: торги 10:00–18:50. Внутридневные сделки собраны по реальному бару '
               f'(открытие {ses["bar"]["open"]}, максимум {ses["bar"]["high"]}, минимум {ses["bar"]["low"]}, закрытие {ses["bar"]["close"]}); API публичных сделок не отдаёт.</p>')
    rows = []
    for when, what, r in ses["events"]:
        if r.get("info"):
            res_html = f'<span class="ok">{E(r["info"])}</span>'
        elif r["accepted"]:
            res_html = f'<span class="ok">принято {r["accepted"]}</span>' + (f', <span class="bad">отклонено {r["rejected"]}</span>' if r["rejected"] else "")
        else:
            res_html = '<span class="bad">отклонено: ' + E(", ".join(r["reject_rules"])) + "</span>"
        rows.append((f"{when:%H:%M:%S}", E(what), res_html))
    out.append('<div class="card">' + table(["Время", "Что происходит", "Результат"], rows) + "</div>")
    c, s = ses["candles"], ses["signal"]
    out.append(f'<div class="grid"><div class="card stat"><b>{c["n"]}</b><span>минутных свечей после закрытия</span></div>'
               f'<div class="card stat"><b>{c["t"]}</b><span>сделок в свечах</span></div>'
               f'<div class="card stat"><b>{E(s["signal"])}</b><span>сигнал по сессии</span></div>'
               f'<div class="card stat"><b>{s["ret"]:+.2%}</b><span>доходность за сессию</span></div></div>')
    out.append('<p class="lead">До закрытия свечей и сигналов нет. Расчёт запускается закрытием сессии, а DAG Airflow стартует в 19:00, после окончания торгов.</p>')

    # 3. тесты
    out.append("<h2>3. Какие есть тесты</h2>")
    if suites:
        tot = sum(len(v) for v in suites.values())
        ok = sum(1 for v in suites.values() for _, st in v if st == "ok")
        bad = sum(1 for v in suites.values() for _, st in v if st == "fail")
        sk = tot - ok - bad
        out.append(f'<div class="grid"><div class="card stat"><b>{tot}</b><span>тестов</span></div>'
                   f'<div class="card stat"><b class="ok">{ok}</b><span>прошли</span></div>'
                   f'<div class="card stat"><b class="{"bad" if bad else "ok"}">{bad}</b><span>упали</span></div>'
                   f'<div class="card stat"><b class="skip">{sk}</b><span>пропущено</span></div></div>')
        cls = {"ok": "ok", "fail": "bad", "skip": "skip"}
        lab = {"ok": "прошёл", "fail": "упал", "skip": "пропущен"}
        for mod in SUITES:
            cases = suites.get(mod)
            if not cases:
                continue
            good = sum(1 for _, st in cases if st == "ok")
            items = "".join(f'<tr><td><code>{E(n)}</code></td><td class="{cls[st]}">{lab[st]}</td></tr>' for n, st in cases)
            out.append(f'<details class="card"><summary>{E(mod)} — {good}/{len(cases)}</summary><p class="lead">{E(SUITES[mod])}</p>'
                       f'<table>{items}</table></details>')
    else:
        out.append('<p class="lead">Результаты тестов не найдены: запустите demo.sh без --skip-tests.</p>')

    # 4. результаты
    out.append("<h2>4. Что получаем в итоге</h2>"
               '<p class="lead">Цены закрытия пяти бумаг, начало периода = 100.</p><div class="card">' + chart(res["series"]) + "</div>")
    rows = []
    for t, m in res["metrics"].items():
        rows.append((f"<b>{E(t)}</b>", f'{m["ret"]:+.2%}', f'{m["vol"]:.1%}', f'{m["max_drawdown"]:.1%}',
                     advisory.risk_class(m["vol"]), f'{m["last_close"]:.2f}'))
    out.append('<div class="card"><b>Показатели за последние 20 сессий</b>' +
               table(["Бумага", "Доходность", "Волатильность (год)", "Макс. просадка", "Класс риска", "Закрытие"], rows, num=(1, 2, 3, 5)) + "</div>")
    ru = {"buy": "покупать", "sell": "продавать", "hold": "держать"}
    for cid, label in ((1, "client-A · консервативный профиль"), (2, "client-B · агрессивный профиль")):
        rows = [(f"<b>{E(r['ticker'])}</b>", f'<b>{ru[r["action"]]}</b>', r["risk_class"], E(r["rationale"])) for r in res["reports"][cid]]
        out.append(f'<div class="card"><b>Рекомендации клиенту {E(label)}</b>' +
                   table(["Бумага", "Действие", "Риск", "Обоснование"], rows) +
                   f'<p class="lead">{E(res["reports"][cid][0]["risk_disclosure"])}</p></div>')
    out.append("<p class='lead'>Рекомендации учебные: импульс за 20 сессий плюс фильтры по риску и доле позиции; это не инвестиционная методика.</p></main></html>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args()

    ch = Db(host=os.getenv("CH_HOST", "127.0.0.1"), port=int(os.getenv("CH_PORT", "8123")), database="demo")
    ch.drop()
    ch = Db(host=os.getenv("CH_HOST", "127.0.0.1"), port=int(os.getenv("CH_PORT", "8123")), database="demo")
    ch.create_schema()
    # данные PostgreSQL держим на диске Linux (NTFS не подходит для кластера); тот же сервер, что в start.sh
    srv = pgserver.get_server(os.getenv("PG_DATA", str(Path.home() / "advisory-stack" / "pgdata")),
                              cleanup_mode=None)
    admin = psycopg2.connect(srv.get_uri()); admin.autocommit = True
    admin.cursor().execute("DROP DATABASE IF EXISTS demo WITH (FORCE)")
    admin.cursor().execute("CREATE DATABASE demo")
    pg = psycopg2.connect(srv.get_uri(database="demo"))
    create_pg_schema(pg)
    s3 = jobs.connect_s3()
    if s3.bucket_exists(RAW_BUCKET):
        for o in s3.list_objects(RAW_BUCKET, recursive=True):
            s3.remove_object(RAW_BUCKET, o.object_name)

    log("1/4 загрузка данных…"); ing = step_ingest(pg, ch, s3, a.offline)
    log("2/4 открытие и закрытие сессии…"); ses = step_session(ch)
    log("3/4 рекомендации…"); res = step_results(pg, ch)
    log("4/4 тесты…"); suites = step_tests(a.skip_tests)
    (OUT / "report.html").write_text(render(ing, ses, res, suites), encoding="utf-8")
    log(f"Готово: {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
