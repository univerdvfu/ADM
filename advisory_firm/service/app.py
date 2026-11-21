"""Маленький сервис: смотреть таблицы PostgreSQL / ClickHouse / MinIO, запускать тесты и следить за ходом.
Запуск: bash deploy/service.sh  →  http://127.0.0.1:8765  (слушает только localhost)
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pgserver
import psycopg2

from analytics_firm import jobs, market_analysis
from analytics_firm.db import Db
from analytics_firm.stack import RAW_BUCKET
from service import openapi, sandbox
from service.tests_meta import DB_TESTS

HOST, PORT = "127.0.0.1", int(os.getenv("SERVICE_PORT", "8765"))
CH_DB = PG_DB = "service"
TICKERS = jobs.DEFAULT_TICKERS
DB_TEST_FILE = ROOT / "tests" / "test_db_complex.py"
INDEX = Path(__file__).resolve().parent / "index.html"
STATIC = Path(__file__).resolve().parent / "static"

_lock = threading.Lock()
_pg_srv = None
RUNS, SEEDS = {}, {}


def _json(o):
    if isinstance(o, (Decimal,)):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat(sep=" ")
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace").strip("\x00 ")
    return str(o)


# ---------- подключения ----------

def pg_server():
    global _pg_srv
    with _lock:
        if _pg_srv is None:
            _pg_srv = pgserver.get_server(os.getenv("PG_DATA", str(Path.home() / "advisory-stack" / "pgdata")),
                                          cleanup_mode=None)
        return _pg_srv


def pg_admin():
    c = psycopg2.connect(pg_server().get_uri())
    c.autocommit = True
    return c


def pg_conn():
    return psycopg2.connect(pg_server().get_uri(database=PG_DB))


def ch_conn():
    return Db(host=os.getenv("CH_HOST", "127.0.0.1"), port=int(os.getenv("CH_PORT", "8123")), database=CH_DB)


def init_storage():
    cur = pg_admin().cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (PG_DB,))
    if not cur.fetchone():
        cur.execute(f"CREATE DATABASE {PG_DB}")
    pg, ch = pg_conn(), ch_conn()
    jobs.ensure_schemas(pg, ch)
    pg.close()


# ---------- данные ----------

def list_tables():
    pg = pg_conn()
    with pg.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")
        names = [r[0] for r in cur.fetchall()]
        out_pg = []
        for n in names:
            cur.execute(f'SELECT count(*) FROM "{n}"')
            out_pg.append({"name": n, "rows": cur.fetchone()[0]})
    pg.close()
    ch = ch_conn()
    out_ch = [{"name": n, "rows": ch.rows(f"SELECT count() n FROM `{n}`")[0]["n"]} for n in sorted(ch.tables())]
    return {"pg": out_pg, "ch": out_ch}


def table_data(db, name, limit, offset):
    known = {t["name"] for t in list_tables()[db]}
    if name not in known:
        raise KeyError(name)
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    if db == "pg":
        pg = pg_conn()
        with pg.cursor() as cur:
            cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (name,))
            cols = [{"name": c, "type": t} for c, t in cur.fetchall()]
            cur.execute(f'SELECT count(*) FROM "{name}"')
            total = cur.fetchone()[0]
            cur.execute(f'SELECT * FROM "{name}" ORDER BY 1 LIMIT %s OFFSET %s', (limit, offset))
            rows = [list(r) for r in cur.fetchall()]
        pg.close()
    else:
        ch = ch_conn()
        cols = [{"name": r["name"], "type": r["type"]} for r in ch.rows(
            "SELECT name, type FROM system.columns WHERE database=%(d)s AND table=%(t)s ORDER BY position",
            {"d": CH_DB, "t": name})]
        total = ch.rows(f"SELECT count() n FROM `{name}`")[0]["n"]
        rows = [list(r.values()) for r in ch.rows(f"SELECT * FROM `{name}` LIMIT {limit} OFFSET {offset}")]
    return {"columns": cols, "rows": rows, "total": total, "limit": limit, "offset": offset}


def minio_list():
    s3 = jobs.connect_s3()
    if not s3.bucket_exists(RAW_BUCKET):
        return []
    return [{"key": o.object_name, "size": o.size} for o in s3.list_objects(RAW_BUCKET, recursive=True)]


def minio_preview(key):
    if key not in {o["key"] for o in minio_list()}:
        raise KeyError(key)
    resp = jobs.connect_s3().get_object(RAW_BUCKET, key)
    try:
        return resp.read(4000).decode("utf-8", "replace")
    finally:
        resp.close(); resp.release_conn()


def _ch_info():
    return ch_conn().rows("SELECT version() v")[0]["v"]


def _pg_info():
    c = pg_conn()
    try:
        with c.cursor() as cur:
            cur.execute("SHOW server_version")
            return cur.fetchone()[0]
    finally:
        c.close()


def _s3_info():
    return f"{len(jobs.connect_s3().list_buckets())} бакетов"


def status():
    out = {}
    for name, fn in (("ClickHouse", _ch_info), ("PostgreSQL", _pg_info), ("MinIO", _s3_info)):
        try:
            out[name] = {"ok": True, "info": str(fn())}
        except Exception as e:
            out[name] = {"ok": False, "info": str(e)[:120]}
    return out


# ---------- загрузка данных ----------

def _run_demo_module():
    spec = importlib.util.spec_from_file_location("run_demo", ROOT / "demo" / "run_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seed_job(job, live, with_day):
    log = job["lines"].append
    try:
        rd = _run_demo_module()
        pg, ch, s3 = pg_conn(), ch_conn(), jobs.connect_s3()
        log("Схемы PostgreSQL и ClickHouse")
        jobs.ensure_schemas(pg, ch)
        day, fetch = date.today(), rd.fixture_fetch
        if live:
            try:
                from analytics_firm import moex
                moex.fetch_security("SBER")
                fetch = None
                log("Источник: живой API Мосбиржи")
            except Exception as e:
                log(f"API недоступен ({e}), беру сохранённые ответы")
        else:
            log("Источник: сохранённые ответы биржи")
        keys = jobs.fetch_raw(s3, TICKERS, day, fetch=fetch)
        log(f"fetch: {len(keys)} файлов сырья сохранено в MinIO")
        ids = jobs.load_from_raw(pg, ch, s3, TICKERS, day, tempfile.mkdtemp())
        log(f"load: справочники и бары загружены, бумаги {ids}")
        q = jobs.quality_check(ch)
        log(f"check: {q['total']} баров, ошибок {q['bad']}")
        with pg.cursor() as cur:
            cur.execute("INSERT INTO advisory_clients VALUES (1,'client-A','conservative',365,30,'active'),"
                        "(2,'client-B','aggressive',90,100,'active') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO positions SELECT 1, ticker_id, 100, 250 FROM tickers WHERE ticker_id<=2 ON CONFLICT DO NOTHING")
        pg.commit()
        if with_day:
            ses = rd.step_session(ch)
            for when, what, r in ses["events"]:
                res = r.get("info") or (f"принято {r['accepted']}" if r["accepted"] else "отклонено: " + ", ".join(r["reject_rules"]))
                log(f"{when:%H:%M:%S}  {what} → {res}")
        from analytics_firm.demo_fill import fill_demo
        fill_demo(pg, ch, s3, log, with_day)
        job["status"] = "done"
        log("Готово")
    except Exception as e:
        job["status"] = "error"
        log(f"Ошибка: {e}")


def reset_job(job):
    log = job["lines"].append
    try:
        ch_conn().drop()
        cur = pg_admin().cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {PG_DB} WITH (FORCE)")
        s3 = jobs.connect_s3()
        if s3.bucket_exists(RAW_BUCKET):
            for o in s3.list_objects(RAW_BUCKET, recursive=True):
                s3.remove_object(RAW_BUCKET, o.object_name)
        init_storage()
        job["status"] = "done"
        log("Базы очищены")
    except Exception as e:
        job["status"] = "error"
        log(f"Ошибка: {e}")


def start_job(fn, *args):
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "status": "running", "lines": []}
    SEEDS[jid] = job
    threading.Thread(target=fn, args=(job, *args), daemon=True).start()
    return jid


# ---------- тесты ----------

def db_tests():
    src = DB_TEST_FILE.read_text(encoding="utf-8")
    out = []
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            meta = DB_TESTS.get(node.name[:7], ("", node.name, "", "", ""))
            out.append({"id": node.name, "num": node.name[5:7], "db": meta[0], "title": meta[1], "essence": meta[2],
                        "how": meta[3], "expected": meta[4], "code": ast.get_source_segment(src, node)})
    return out


def start_run(targets):
    rid = uuid.uuid4().hex[:8]
    trace = Path(tempfile.gettempdir()) / f"trace_{rid}.jsonl"
    trace.write_text("")
    run = {"id": rid, "status": "running", "lines": [], "tests": {}, "pos": 0, "trace": trace, "started": time.time(), "rc": None}
    env = dict(os.environ, TEST_TRACE=str(trace), PYTHONUNBUFFERED="1")
    cmd = [sys.executable, "-m", "pytest", "-vv", "-p", "no:cacheprovider", "-W", "ignore", "--no-header", *targets]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    run["proc"] = proc

    def reader():
        for line in proc.stdout:
            run["lines"].append(line.rstrip())
        proc.wait()
        run["rc"] = proc.returncode
        run["status"] = "done"
        run["finished"] = time.time()
    threading.Thread(target=reader, daemon=True).start()
    RUNS[rid] = run
    return rid


def pump(run):
    with open(run["trace"], "rb") as f:
        f.seek(run["pos"])
        data = f.read()
    last = data.rfind(b"\n")
    if last < 0:
        return
    run["pos"] += last + 1
    for line in data[:last + 1].decode("utf-8", "replace").splitlines():
        ev = json.loads(line)
        t = run["tests"].setdefault(ev["test"], {"status": "pending", "sql": [], "duration": None, "error": ""})
        if ev["t"] == "start":
            t["status"] = "running"
        elif ev["t"] == "sql" and len(t["sql"]) < 300:
            t["sql"].append({k: ev[k] for k in ("db", "sql", "ms", "rows")})
        elif ev["t"] == "end":
            t.update(status={"passed": "passed", "failed": "failed", "skipped": "skipped"}.get(ev["outcome"], "error"),
                     duration=ev["duration"], error=ev["error"])


def run_view(run):
    pump(run)
    elapsed = (run.get("finished") or time.time()) - run["started"]
    return {"id": run["id"], "status": run["status"], "rc": run["rc"], "elapsed": round(elapsed, 1),
            "lines": run["lines"][-400:], "tests": run["tests"]}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=_json).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_500_000:
            raise ValueError("слишком большой запрос")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/openapi.json":
                return self.send(200, openapi.spec())
            if u.path in ("/docs", "/docs/"):
                return self.send(200, openapi.DOCS_HTML.encode("utf-8"), "text/html; charset=utf-8")
            if u.path in ("/static/swagger-ui.css", "/static/swagger-ui-bundle.js"):
                name = u.path.rsplit("/", 1)[1]
                ctype = "text/css" if name.endswith(".css") else "application/javascript"
                return self.send(200, (STATIC / name).read_bytes(), ctype + "; charset=utf-8")
            if u.path == "/api/status":
                return self.send(200, status())
            if u.path == "/api/tables":
                return self.send(200, list_tables())
            if u.path == "/api/table":
                return self.send(200, table_data(q["db"], q["name"], int(q.get("limit", 30)), int(q.get("offset", 0))))
            if u.path == "/api/market/sessions":
                ticker = int(q["ticker_id"]) if q.get("ticker_id") else None
                return self.send(200, market_analysis.market_sessions(ch_conn(), ticker))
            if u.path == "/api/market/twins":
                return self.send(200, market_analysis.find_twins(
                    ch_conn(), int(q["ticker_id"]), int(q["session_id"]), q.get("end"),
                    int(q.get("length", 20)), int(q.get("limit", 5))))
            if u.path == "/api/market/butterfly":
                return self.send(200, market_analysis.butterfly_effect(
                    ch_conn(), int(q["ticker_id"]), int(q["session_id"]), q.get("start"), q.get("end"),
                    float(q.get("top_percent", 1))))
            if u.path == "/api/minio":
                return self.send(200, minio_list())
            if u.path == "/api/minio/object":
                return self.send(200, {"text": minio_preview(q["key"])})
            if u.path == "/api/tests":
                return self.send(200, db_tests())
            if u.path.startswith("/api/run/"):
                return self.send(200, run_view(RUNS[u.path.rsplit("/", 1)[1]]))
            if u.path.startswith("/api/job/"):
                return self.send(200, SEEDS[u.path.rsplit("/", 1)[1]])
            self.send(404, {"error": "not found"})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except KeyError as e:
            self.send(404, {"error": f"не найдено: {e}"})
        except Exception as e:
            self.send(500, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            b = self.body()
            if u.path == "/api/run":
                if b.get("tests"):
                    ids = {t["id"] for t in db_tests()}
                    targets = [f"tests/test_db_complex.py::{t}" for t in b["tests"] if t in ids]
                else:
                    targets = ["tests/test_db_complex.py"]
                return self.send(200, {"id": start_run(targets)})
            if u.path.endswith("/stop"):
                RUNS[u.path.split("/")[3]]["proc"].terminate()
                return self.send(200, {"ok": True})
            if u.path == "/api/ingest":
                # тело запроса — сам JSON: список записей или таблица trades в формате ISS Мосбиржи
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                ch = ch_conn()
                if q.get("dry") == "1":
                    return self.send(200, sandbox.check(ch, b))
                pg = pg_conn()
                try:
                    return self.send(200, sandbox.send(ch, pg, jobs.connect_s3(), b, q.get("candles") == "1"))
                finally:
                    pg.close()
            if u.path == "/api/ingest/session":
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self.send(200, sandbox.set_session(ch_conn(), "closed" if q.get("status") == "closed" else "open"))
            if u.path == "/api/ingest/reset":
                return self.send(200, sandbox.reset(ch_conn()))
            if u.path == "/api/seed":
                return self.send(200, {"id": start_job(seed_job, bool(b.get("live")), bool(b.get("day", True)))})
            if u.path == "/api/reset":
                return self.send(200, {"id": start_job(reset_job)})
            self.send(404, {"error": "not found"})
        except Exception as e:
            self.send(500, {"error": str(e)})


def main():
    init_storage()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сервис: http://{HOST}:{PORT}  (Ctrl+C — остановить)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
