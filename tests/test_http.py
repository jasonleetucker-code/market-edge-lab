import http.client
from urllib.error import URLError

import pytest

from conftest import ScriptedOpener, http_error
from edge_lab.http import HttpFetchError, fetch, fetch_json_result


def _no_sleep(recorder):
    return lambda seconds: recorder.append(seconds)


def test_fetch_records_provenance():
    opener = ScriptedOpener({"ok": True})
    result = fetch("https://example.test/a", opener=opener, sleep=lambda s: None)
    assert result.http_status == 200
    assert result.attempts == 1
    assert result.requested_url == "https://example.test/a"
    assert result.content_type == "application/json"
    assert result.received_at_utc.endswith("+00:00")
    assert opener.calls == ["GET https://example.test/a"]


def test_transient_errors_retry_with_backoff():
    slept: list[float] = []
    opener = ScriptedOpener(http_error(503), URLError("reset"), {"ok": True})
    payload, result = fetch_json_result(
        "https://example.test/a", opener=opener, retries=2, backoff=0.5, sleep=_no_sleep(slept),
        jitter=lambda: 0.0,
    )
    assert payload == {"ok": True}
    assert result.attempts == 3
    assert slept == [0.5, 1.0]
    assert result.retry_reasons == ("http_503", "URLError")


def test_retry_after_is_honored_and_capped():
    slept: list[float] = []
    opener = ScriptedOpener(http_error(429, "7"), http_error(429, "9999"), {"ok": 1})
    fetch("https://example.test/a", opener=opener, retries=2, sleep=_no_sleep(slept))
    assert slept == [7.0, 30.0]


def test_client_errors_do_not_retry():
    opener = ScriptedOpener(http_error(404), {"never": "reached"})
    with pytest.raises(HttpFetchError) as info:
        fetch("https://example.test/a", opener=opener, retries=3, sleep=lambda s: None)
    assert info.value.status == 404
    assert info.value.attempts == 1
    assert len(opener.calls) == 1


def test_retries_are_bounded():
    opener = ScriptedOpener(http_error(500), http_error(500), http_error(500))
    with pytest.raises(HttpFetchError) as info:
        fetch("https://example.test/a", opener=opener, retries=2, sleep=lambda s: None)
    assert info.value.attempts == 3


def test_non_object_json_is_rejected():
    opener = ScriptedOpener([1, 2, 3])
    with pytest.raises(HttpFetchError):
        fetch_json_result("https://example.test/a", opener=opener, sleep=lambda s: None)


def test_invalid_json_is_rejected():
    opener = ScriptedOpener(b"<html>maintenance</html>")
    with pytest.raises(HttpFetchError):
        fetch_json_result("https://example.test/a", opener=opener, sleep=lambda s: None)


def test_low_level_transport_errors_retry_and_are_wrapped():
    opener = ScriptedOpener(
        http.client.RemoteDisconnected("closed"), ConnectionResetError("reset"), {"ok": True}
    )
    result = fetch("https://example.test/a", opener=opener, retries=2, sleep=lambda s: None)
    assert result.attempts == 3

    opener = ScriptedOpener(http.client.IncompleteRead(b""), http.client.IncompleteRead(b""))
    with pytest.raises(HttpFetchError) as info:
        fetch("https://example.test/a", opener=opener, retries=1, sleep=lambda s: None)
    assert info.value.attempts == 2


def test_backoff_jitter_is_bounded():
    slept: list[float] = []
    opener = ScriptedOpener(http_error(429), {"ok": True})
    fetch("https://example.test/a", opener=opener, backoff=1.0, sleep=_no_sleep(slept), jitter=lambda: 1.0)
    assert slept == [1.5]  # at most +50%


def test_pacer_enforces_min_interval():
    from edge_lab.http import Pacer

    now = [0.0]
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    pacer = Pacer(0.6, clock=lambda: now[0], sleep=sleep)
    pacer.wait()  # first call never waits
    now[0] += 0.1
    pacer.wait()
    now[0] += 1.0
    pacer.wait()  # enough time passed
    assert slept == [pytest.approx(0.5)]
