"""Задачи DAG Airflow: сырьё -> MinIO -> PostgreSQL/ClickHouse -> проверка -> рекомендации."""
import json
from datetime import date
from pathlib import Path

import pytest

from analytics_firm import jobs
from conftest import FIX

MOEX = FIX / "moex"
TICKERS = ["SBER", "GAZP"]
DAY = date(2026, 10, 29)


def fake_fetch(secid, start, end):
    load = lambda n: json.loads((MOEX / n).read_text(encoding="utf-8"))
    return load(f"hist_{secid}.json"), load(f"sec_{secid}.json")


@pytest.fixture
def loaded(pg, db, s3, tmp_path):
    keys = jobs.fetch_raw(s3, TICKERS, DAY, fetch=fake_fetch)
    ids = jobs.load_from_raw(pg, db, s3, TICKERS, DAY, tmp_path / "raw")
    return pg, db, s3, keys, ids


def test_fetch_puts_raw_responses_into_minio(loaded):
    pg, db, s3, keys, ids = loaded
    assert sorted(keys) == sorted(f"moex/{DAY}/{k}_{t}.json" for t in TICKERS
                                  for k in ("hist", "sec"))
    stored = {o.object_name for o in s3.list_objects("raw-market", recursive=True)}
    assert set(keys) <= stored


def test_load_from_raw_fills_postgres_and_clickhouse(loaded):
    pg, db, s3, keys, ids = loaded
    assert ids == {"SBER": 1, "GAZP": 2}
    assert db.rows("SELECT uniqExact(ticker_id) n FROM daily_bars FINAL")[0]["n"] == 2
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM tickers")
        assert cur.fetchone()[0] == 2


def test_quality_check_passes_then_fails_on_corrupt_bar(loaded):
    pg, db, s3, keys, ids = loaded
    assert jobs.quality_check(db)["bad"] == "0"
    db.command("INSERT INTO daily_bars VALUES ('MOEX-ISS',1,99999999,'2026-11-01',10,5,20,30,"
               "1,1,1,now64(3))")                       # high < low
    with pytest.raises(ValueError):
        jobs.quality_check(db)


def test_refresh_recommendations_is_idempotent(loaded):
    pg, db, s3, keys, ids = loaded
    with pg.cursor() as cur:
        cur.execute("INSERT INTO advisory_clients VALUES (1,'c','moderate',90,50,'active')")
    pg.commit()
    first = jobs.refresh_recommendations(pg, db)
    assert first == 2
    assert jobs.refresh_recommendations(pg, db) == 0
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM recommendations WHERE author='airflow-bot'")
        assert cur.fetchone()[0] == 2


def test_dag_structure():
    airflow = pytest.importorskip("airflow")
    from airflow.models import DagBag
    bag = DagBag(str(Path(__file__).resolve().parent.parent / "dags"), include_examples=False)
    assert not bag.import_errors
    dag = bag.get_dag("advisory_pipeline")
    order = [t.task_id for t in dag.topological_sort()]
    assert order == ["init", "fetch", "load", "check", "recommend"]
    assert dag.schedule_interval == "0 19 * * 1-5" and dag.catchup is False
