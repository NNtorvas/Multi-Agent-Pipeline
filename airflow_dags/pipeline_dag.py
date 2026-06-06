import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# Make project root importable inside the Airflow container
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.graph import run_pipeline  # noqa: E402
from utils.db import init_db, save_report  # noqa: E402

_DEFAULT_ARGS = {
    "owner": "ml-engineer",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


def _run_analysis_pipeline(**context) -> None:
    logging.info("[dag] Starting weather analysis pipeline run")
    init_db()

    result = run_pipeline()

    report_md = result.get("report") or "Report generation failed — check pipeline logs."
    status = result.get("status", "unknown")
    errors = result.get("errors", [])

    if errors:
        logging.warning("[dag] Pipeline completed with %d error(s): %s", len(errors), errors)

    report_id = save_report(report_md, status)
    logging.info("[dag] Run complete — report_id=%d status=%s", report_id, status)
    context["ti"].xcom_push(key="report_id", value=report_id)


with DAG(
    dag_id="weather_analysis_pipeline",
    default_args=_DEFAULT_ARGS,
    description="Daily multi-agent weather analysis using LangGraph + Claude",
    schedule_interval="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["weather", "ml", "langgraph", "anthropic"],
) as dag:
    run_task = PythonOperator(
        task_id="run_pipeline",
        python_callable=_run_analysis_pipeline,
    )
