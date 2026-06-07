import json
import logging

from pipeline.state import PipelineState
from utils.claude_wrapper import call_claude

_SYSTEM = """\
You are a meteorological data analyst. Given a 7-day weather forecast as JSON,
respond with ONLY valid JSON matching this exact schema — no markdown fences, no prose:
{
  "observations": ["<string>", "<string>", "<string>"],
  "anomaly_flag": <boolean>,
  "anomaly_description": "<string — empty if no anomaly>",
  "trend_summary": "<one sentence>",
  "risk_level": "<low|medium|high>"
}
observations must contain at least 3 distinct items."""

_FALLBACK: dict = {
    "observations": [
        "Weather data unavailable — analysis skipped.",
        "Trend detection requires valid forecast input.",
        "Fallback mode active due to upstream failure.",
    ],
    "anomaly_flag": False,
    "anomaly_description": "",
    "trend_summary": "Analysis could not be completed due to missing data.",
    "risk_level": "low",
}


def run_analysis_agent(state: PipelineState) -> dict:
    logging.info("[analysis_agent] Running Claude trend/anomaly analysis")
    weather_data = state.get("weather_data") or {}

    if not weather_data.get("days"):
        logging.warning("[analysis_agent] No forecast days — using fallback analysis")
        return {"analysis": _FALLBACK, "status": "analysis_skipped"}

    prompt = (
        "Analyse this 7-day weather forecast for Paris."
        " Detect trends, anomalies, and risks:\n" + json.dumps(weather_data, indent=2)
    )
    try:
        raw = call_claude(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=512,
        )
        analysis = json.loads(raw)
        logging.info(
            "[analysis_agent] Analysis complete — anomaly_flag=%s",
            analysis.get("anomaly_flag"),
        )
        return {"analysis": analysis, "status": "analysis_complete"}
    except Exception as exc:
        logging.error("[analysis_agent] Failed: %s", exc)
        return {
            "analysis": _FALLBACK,
            "errors": state["errors"] + [f"analysis_agent: {exc}"],
            "status": "analysis_failed",
        }
