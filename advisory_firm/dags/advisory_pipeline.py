"""DAG: после закрытия сессии берём данные Мосбиржи и обновляем аналитику (слайд 5: Airflow)."""
from datetime import date, datetime

from airflow.decorators import dag, task

from analytics_firm import jobs

TICKERS = jobs.DEFAULT_TICKERS


@dag(dag_id="advisory_pipeline", schedule="0 19 * * 1-5", start_date=datetime(2026, 10, 1),
     catchup=False, max_active_runs=1, tags=["moex", "advisory"],
     default_args={"retries": 2})
def advisory_pipeline():
    @task
    def init():
        pg, ch = jobs.connect_pg(), jobs.connect_ch()
        return jobs.ensure_schemas(pg, ch)

    @task
    def fetch(ds=None):
        return jobs.fetch_raw(jobs.connect_s3(), TICKERS, date.fromisoformat(ds))

    @task
    def load(ds=None):
        report = {}
        ids = jobs.load_from_raw(jobs.connect_pg(), jobs.connect_ch(), jobs.connect_s3(),
                                 TICKERS, date.fromisoformat(ds), "/tmp/moex_raw", report)
        # бары проверяются до записи: брак уходит в карантин с кодом причины и в daily_bars не попадает
        return {"tickers": ids, "accepted": report.get("accepted"), "rejected": report.get("rejected"),
                "reject_rules": report.get("reject_rules")}

    @task
    def check():
        return jobs.quality_check(jobs.connect_ch())

    @task
    def recommend():
        return jobs.refresh_recommendations(jobs.connect_pg(), jobs.connect_ch())

    init() >> fetch() >> load() >> check() >> recommend()


advisory_pipeline()
