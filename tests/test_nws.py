import pytest

from edge_lab.nws import forecast_urls


def test_forecast_urls_uses_links_discovered_from_points():
    payload = {
        "properties": {
            "forecast": "https://api.weather.gov/gridpoints/OKX/33,37/forecast",
            "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,37/forecast/hourly",
            "forecastGridData": "https://api.weather.gov/gridpoints/OKX/33,37",
        }
    }

    assert forecast_urls(payload) == {
        "forecast": "https://api.weather.gov/gridpoints/OKX/33,37/forecast",
        "forecast_hourly": "https://api.weather.gov/gridpoints/OKX/33,37/forecast/hourly",
        "forecast_grid": "https://api.weather.gov/gridpoints/OKX/33,37",
    }


def test_forecast_urls_rejects_missing_links():
    with pytest.raises(ValueError):
        forecast_urls({"properties": {"forecast": "https://example.test"}})
