"""SVC-REQUEST-LATENCY-1 client seam: correlation id out, timing back."""

import logging

import httpx
import pytest

from smartmemory_client import RemoteCallTiming, SmartMemoryClient
from smartmemory_client.client import SmartMemoryServerError


def _client(handler, **kwargs) -> SmartMemoryClient:
    client = SmartMemoryClient(
        base_url="http://svc.test", api_key="sm_test_key", **kwargs
    )
    # Keep the event hooks the constructor installed; swap only the transport.
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        event_hooks=client._client.event_hooks,
    )
    return client


def _ok(headers=None):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.seen = request
        return httpx.Response(200, json={"ok": True}, headers=headers or {})

    handler.seen = None
    return handler


def test_no_provider_sends_no_request_id():
    handler = _ok()
    client = _client(handler)
    client._request("GET", "/memory/x")
    assert "X-Request-Id" not in handler.seen.headers


def test_request_id_is_sent_and_timing_reported():
    handler = _ok(headers={"X-SM-Latency-Ms": "12.50"})
    seen: list[RemoteCallTiming] = []
    client = _client(
        handler, request_id_provider=lambda: "turn-7", on_remote_call=seen.append
    )
    client._request("GET", "/memory/x")

    assert handler.seen.headers["X-Request-Id"] == "turn-7"
    (timing,) = seen
    assert timing.method == "GET"
    assert timing.path == "/memory/x"
    assert timing.status_code == 200
    assert timing.server_ms == 12.50
    assert timing.wall_ms >= 0.0
    assert timing.request_id == "turn-7"


def test_missing_latency_header_reports_none_not_zero():
    # None means "unknown"; 0.0 would claim the service answered instantly.
    seen: list[RemoteCallTiming] = []
    client = _client(_ok(), on_remote_call=seen.append)
    client._request("GET", "/memory/x")
    assert seen[0].server_ms is None


def test_malformed_latency_header_warns_and_still_reports(caplog):
    seen: list[RemoteCallTiming] = []
    client = _client(
        _ok(headers={"X-SM-Latency-Ms": "fast"}), on_remote_call=seen.append
    )
    with caplog.at_level(logging.WARNING, logger="smartmemory_client.client"):
        client._request("GET", "/memory/x")
    assert seen[0].server_ms is None
    assert any("unparseable" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("bad", ["has space", "a" * 65, "nl\nline"])
def test_invalid_request_id_is_dropped_with_warning(bad, caplog):
    handler = _ok()
    client = _client(handler, request_id_provider=lambda: bad)
    with caplog.at_level(logging.WARNING, logger="smartmemory_client.client"):
        client._request("GET", "/memory/x")
    assert "X-Request-Id" not in handler.seen.headers
    assert any("rejected" in r.getMessage() for r in caplog.records)


def test_provider_failure_never_fails_the_request(caplog):
    handler = _ok()

    def boom():
        raise RuntimeError("no id")

    client = _client(handler, request_id_provider=boom)
    with caplog.at_level(logging.WARNING, logger="smartmemory_client.client"):
        assert client._request("GET", "/memory/x") == {"ok": True}
    assert "X-Request-Id" not in handler.seen.headers
    assert any("lost=X-Request-Id" in r.getMessage() for r in caplog.records)


def test_observer_failure_never_fails_the_request(caplog):
    def boom(_timing):
        raise RuntimeError("bad observer")

    client = _client(_ok(), on_remote_call=boom)
    with caplog.at_level(logging.WARNING, logger="smartmemory_client.client"):
        assert client._request("GET", "/memory/x") == {"ok": True}
    assert any("discarded" in r.getMessage() for r in caplog.records)


def test_error_responses_are_still_timed():
    seen: list[RemoteCallTiming] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500, json={"detail": "nope"}, headers={"X-SM-Latency-Ms": "3.0"}
        )

    client = _client(handler, on_remote_call=seen.append)
    with pytest.raises(SmartMemoryServerError):
        client._request("GET", "/memory/x")
    assert seen[0].status_code == 500
    assert seen[0].server_ms == 3.0
