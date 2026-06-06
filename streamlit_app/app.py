import os
import sys
from pathlib import Path
from datetime import datetime

import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import init_db, get_all_reports, get_report_by_id  # noqa: E402

_AIRFLOW_BASE = os.environ.get("AIRFLOW_BASE_URL", "http://airflow-webserver:8080")
_AIRFLOW_USER = os.environ.get("AIRFLOW_USER", "admin")
_AIRFLOW_PASS = os.environ.get("AIRFLOW_PASS", "admin")
_DAG_ID = "weather_analysis_pipeline"

st.set_page_config(page_title="Weather Analysis Pipeline", layout="wide")
st.title("Multi-Agent Weather Analysis Pipeline")
st.caption("Powered by LangGraph · Claude · ChromaDB · Open-Meteo")


def _trigger_dag() -> tuple[bool, str]:
    url = f"{_AIRFLOW_BASE}/api/v1/dags/{_DAG_ID}/dagRuns"
    run_id = f"manual_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
    try:
        resp = requests.post(
            url,
            json={"conf": {}, "dag_run_id": run_id},
            auth=(_AIRFLOW_USER, _AIRFLOW_PASS),
            timeout=10,
        )
        resp.raise_for_status()
        return True, resp.json().get("dag_run_id", run_id)
    except Exception as exc:
        return False, str(exc)


# Ensure table exists (idempotent)
try:
    init_db()
except Exception:
    pass

# ── Header row: title + run-now button ──────────────────────────────────────
col_title, col_btn = st.columns([5, 1])
with col_title:
    st.subheader("Past Reports")
with col_btn:
    if st.button("▶ Run Now", type="primary", use_container_width=True):
        ok, info = _trigger_dag()
        if ok:
            st.toast(f"DAG triggered: {info}", icon="✅")
        else:
            st.error(f"Could not trigger DAG: {info}")

# ── Reports table ────────────────────────────────────────────────────────────
try:
    reports = get_all_reports()
except Exception as exc:
    st.error(f"Could not load reports from database: {exc}")
    reports = []

if not reports:
    st.info("No reports yet. Click **▶ Run Now** to generate the first one.")
else:
    for report_id, created_at, status in reports:
        c_id, c_ts, c_status, c_btn = st.columns([1, 3, 2, 2])
        c_id.write(f"**#{report_id}**")
        c_ts.write(str(created_at)[:19])
        badge = ":green[complete]" if status == "complete" else f":orange[{status}]"
        c_status.markdown(badge)
        if c_btn.button("View", key=f"view_{report_id}"):
            st.session_state["selected"] = report_id

# ── Report viewer ────────────────────────────────────────────────────────────
if "selected" in st.session_state:
    rid = st.session_state["selected"]
    try:
        row = get_report_by_id(rid)
    except Exception as exc:
        st.error(f"Could not load report #{rid}: {exc}")
        row = None

    if row:
        st.divider()
        st.subheader(f"Report #{row[0]}  ·  {str(row[1])[:19]}  ·  status: {row[3]}")
        st.markdown(row[2])
    elif row is None and "selected" in st.session_state:
        st.warning(f"Report #{rid} not found.")
