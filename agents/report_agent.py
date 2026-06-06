import json
import logging

from pipeline.state import PipelineState
from utils.claude_wrapper import call_claude

_SYSTEM = """\
You are a senior weather analyst writing an executive briefing. \
Generate a professional markdown report with exactly these four sections in order:
## Summary
## Key Findings
## Historical Context
## Recommended Actions

Rules: use bullet points in Key Findings and Recommended Actions; \
be concise and actionable; do not add extra sections or commentary outside the four headers."""

_FALLBACK = """\
## Summary
The analysis pipeline encountered errors and could not produce a complete report.

## Key Findings
- One or more pipeline stages failed during this run.
- Partial data may be available in the pipeline logs.

## Historical Context
- Historical context retrieval was not completed.

## Recommended Actions
- Review `logs/token_usage.log` and Airflow task logs for error details.
- Re-trigger the pipeline after resolving the underlying issue.
"""


def run_report_agent(state: PipelineState) -> dict:
    logging.info("[report_agent] Synthesising markdown report")
    weather_data = state.get("weather_data") or {}
    analysis = state.get("analysis") or {}
    context_docs = state.get("context_docs") or []

    context_block = "\n".join(f"- {doc}" for doc in context_docs)
    prompt = f"""Synthesise the following inputs into a weather analysis report.

**7-Day Forecast (Paris):**
{json.dumps(weather_data.get("days", []), indent=2)}

**Automated Analysis:**
{json.dumps(analysis, indent=2)}

**Relevant Historical Events from Knowledge Base:**
{context_block}
"""
    try:
        report = call_claude(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=1024,
        )
        logging.info("[report_agent] Report generated (%d chars)", len(report))
        return {"report": report, "status": "complete"}
    except Exception as exc:
        logging.error("[report_agent] Failed: %s", exc)
        return {
            "report": _FALLBACK,
            "errors": state["errors"] + [f"report_agent: {exc}"],
            "status": "report_failed",
        }
