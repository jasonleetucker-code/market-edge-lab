from __future__ import annotations

from typing import Any

from .http import fetch_json
from .storage import SnapshotStore

BASE_URL = "https://api.weather.gov"
DEFAULT_LAT = 40.7812
DEFAULT_LON = -73.9665


def forecast_urls(points_payload: dict[str, Any]) -> dict[str, str]:
    properties = points_payload.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("NWS points payload missing properties")

    keys = {
        "forecast": "forecast",
        "forecast_hourly": "forecastHourly",
        "forecast_grid": "forecastGridData",
    }
    result: dict[str, str] = {}

    for kind, prop_name in keys.items():
        value = properties.get(prop_name)
        if not isinstance(value, str) or not value.startswith("https://"):
            raise ValueError(f"NWS points payload missing valid {prop_name}")
        result[kind] = value

    return result


def collect_reference_forecast(
    store: SnapshotStore,
    *,
    run_id: str,
    user_agent: str,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
) -> dict[str, int]:
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    point_id = f"{lat:.4f},{lon:.4f}"
    points_url = f"{BASE_URL}/points/{point_id}"

    points_payload = fetch_json(points_url, headers=headers)
    store.save_snapshot(
        run_id=run_id,
        source="nws",
        kind="points",
        entity_id=point_id,
        url=points_url,
        payload=points_payload,
    )

    urls = forecast_urls(points_payload)
    counts = {"points": 1, "forecast": 0, "forecast_hourly": 0, "forecast_grid": 0}

    for kind, url in urls.items():
        payload = fetch_json(url, headers=headers)
        properties = payload.get("properties")
        source_timestamp = None
        if isinstance(properties, dict):
            source_timestamp = properties.get("updateTime") or properties.get("updated")

        store.save_snapshot(
            run_id=run_id,
            source="nws",
            kind=kind,
            entity_id=point_id,
            url=url,
            payload=payload,
            source_timestamp_utc=str(source_timestamp) if source_timestamp else None,
        )
        counts[kind] += 1

    return counts
