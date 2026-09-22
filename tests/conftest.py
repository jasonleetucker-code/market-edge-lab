from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, url: str = "", content_type: str = "application/json"):
        self._body = body
        self.status = status
        self._url = url
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ScriptedOpener:
    """Opener that replays a scripted sequence of responses/exceptions."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls: list[str] = []

    def __call__(self, request, timeout):
        self.calls.append(request.get_method() + " " + request.full_url)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, (dict, list)):
            return FakeResponse(json.dumps(step).encode(), url=request.full_url)
        return FakeResponse(step, url=request.full_url)


def http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return HTTPError("https://example.test", code, "err", headers, None)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
