"""http.fetch opt-ins for feeds (#192, ADR 0049): byte cap, 304 results, conditional-GET validators.

Defaults are unchanged for every existing caller; these tests use a fake opener (no network)."""

from __future__ import annotations

import io
from email.message import Message
from urllib.error import HTTPError

import pytest

from edge_lab.http import HttpFetchError, allowlisted_headers, fetch


class Resp:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._b = io.BytesIO(body)
        self.status = 200
        self.headers = Message()
        for k, v in headers.items():
            self.headers[k] = v

    def read(self, n=-1):
        return self._b.read(n)

    def geturl(self):
        return "https://example.org/feed"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(body=b"<rss/>", headers=None):
    return lambda req, timeout: Resp(body, headers or {"ETag": '"v1"', "Last-Modified": "Thu, 05 Nov 2026 13:00:00 GMT",
                                                      "Set-Cookie": "secret=1"})


def test_defaults_are_unchanged():
    res = fetch("https://example.org/feed", opener=opener_for())
    assert res.response_headers == ()  # validators are dropped unless opted in, cookies always


def test_validators_are_kept_only_when_opted_in():
    res = fetch("https://example.org/feed", opener=opener_for(), extra_response_headers=("etag", "last-modified"))
    assert dict(res.response_headers) == {"etag": '"v1"', "last-modified": "Thu, 05 Nov 2026 13:00:00 GMT"}
    with pytest.raises(ValueError):
        fetch("https://example.org/feed", opener=opener_for(), extra_response_headers=("set-cookie",))
    msg = Message()
    msg["X-Requests-Remaining"] = "5"
    msg["ETag"] = "x"
    assert allowlisted_headers(msg) == (("x-requests-remaining", "5"),)


def test_max_bytes_refuses_oversize_bodies():
    with pytest.raises(HttpFetchError, match="exceeds 10 bytes"):
        fetch("https://example.org/feed", opener=opener_for(b"x" * 11), max_bytes=10, retries=0)
    assert fetch("https://example.org/feed", opener=opener_for(b"x" * 10), max_bytes=10).body == b"x" * 10


def test_304_is_a_result_only_when_accepted():
    def not_modified(req, timeout):
        hdrs = Message()
        hdrs["ETag"] = '"v1"'
        raise HTTPError("https://example.org/feed", 304, "Not Modified", hdrs, io.BytesIO(b""))

    with pytest.raises(HttpFetchError) as err:
        fetch("https://example.org/feed", opener=not_modified, retries=0)
    assert err.value.status == 304
    res = fetch("https://example.org/feed", opener=not_modified, accept_not_modified=True,
                extra_response_headers=("etag",))
    assert res.http_status == 304 and res.body == b"" and dict(res.response_headers) == {"etag": '"v1"'}
