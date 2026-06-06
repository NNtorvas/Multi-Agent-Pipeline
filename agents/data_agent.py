import logging
from datetime import datetime

import requests

from pipeline.state import PipelineState
from utils.claude_wrapper import retry

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@retry(max_retries=3, base_delay=1.0)
def _fetch_weather() -> dict:
    params = {
        "latitude": 48.8566,
        "longitude": 2.3522,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
        "timezone": "Europe/Paris",
        "forecast_days": 7,
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)
    resp.raise_for_status()
    raw = resp.json()
    daily = raw["daily"]

    days = [
        {
            "date": date,
            "temp_max": daily["temperature_2m_max"][i],
            "temp_min": daily["temperature_2m_min"][i],
            "precipitation": daily["precipitation_sum"][i],
            "windspeed_max": daily["windspeed_10m_max"][i],
        }
        for i, date in enumerate(daily["time"])
    ]
    return {
        "location": "Paris, France",
        "retrieved_at": datetime.utcnow().isoformat(),
        "days": days,
    }


def run_data_agent(state: PipelineState) -> dict:
    logging.info("[data_agent] Fetching 7-day forecast from Open-Meteo")
    try:
        data = _fetch_weather()
        logging.info("[data_agent] Fetched %d days of data", len(data["days"]))
        return {"weather_data": data, "status": "data_complete"}
    except Exception as exc:
        logging.error("[data_agent] Failed: %s", exc)
        return {
            "weather_data": {"location": "Paris, France", "days": [], "error": str(exc)},
            "errors": state["errors"] + [f"data_agent: {exc}"],
            "status": "data_failed",
        }
