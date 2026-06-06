"""
Local CLI runner — executes the full pipeline without Airflow or Docker.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python main.py

Set DATABASE_URL to also persist the report to PostgreSQL.
"""
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

if "ANTHROPIC_API_KEY" not in os.environ:
    print("ERROR: ANTHROPIC_API_KEY environment variable is not set.")
    sys.exit(1)

from pipeline.graph import run_pipeline  # noqa: E402

if __name__ == "__main__":
    print("\n=== Multi-Agent Weather Analysis Pipeline ===\n")
    result = run_pipeline()

    print(f"\nStatus : {result['status']}")
    if result["errors"]:
        print(f"Errors : {result['errors']}")

    report = result.get("report", "")
    if report:
        print("\n" + "─" * 60)
        print(report)
        print("─" * 60)

    if os.environ.get("DATABASE_URL"):
        from utils.db import init_db, save_report  # noqa: E402
        init_db()
        rid = save_report(report, result["status"])
        print(f"\nSaved to PostgreSQL — report id={rid}")
