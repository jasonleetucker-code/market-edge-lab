from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpFetchError(RuntimeError):
    """Raised when a public data endpoint cannot be fetched or decoded."""


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "market-edge-lab/0.1",
    }
    if headers:
        request_headers.update(headers)

    request = Request(url, headers=request_headers, method="GET")

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        raise HttpFetchError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise HttpFetchError(f"Network error fetching {url}: {exc.reason}") from exc

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HttpFetchError(f"Invalid JSON returned by {url}") from exc

    if not isinstance(payload, dict):
        raise HttpFetchError(f"Expected a JSON object from {url}, got {type(payload).__name__}")

    return payload
