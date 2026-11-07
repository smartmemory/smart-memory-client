"""SDKJS-2.0-STAGE-RETRY-NO-REPLAY-1: count real client/httpx transport sends offline."""
import json
import socket
from pathlib import Path

import httpx
import pytest

from smartmemory_client import SmartMemoryClient, SmartMemoryClientError
from smartmemory_client import _save_transport as transport


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("test_retry: network forbidden")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(transport.time, "sleep", lambda _: None)


CALLS = [
    ("add", lambda c: c.add("test_retry note", idempotency_key="test_retry_key")),
    ("ingest", lambda c: c.ingest("test_retry note", idempotency_key="test_retry_key")),
    ("document", lambda c: c.ingest_document("https://example.test/a.pdf", idempotency_key="test_retry_key")),
]
FIXTURE = json.loads((Path(__file__).parent / "data/save_receipt_fixtures.json").read_text())["pending_save"]


@pytest.mark.parametrize("name,call", CALLS, ids=[r[0] for r in CALLS])
@pytest.mark.parametrize("failure", ["read_timeout", 408, 500, 502, 503, 504])
def test_ambiguous_write_is_never_repeated(name, call, failure):
    committed = []
    def send(request):
        committed.append(request.content)
        if failure == "read_timeout":
            raise httpx.ReadTimeout("test_retry: committed then response dropped", request=request)
        return httpx.Response(failure, json={}, request=request)
    with SmartMemoryClient(base_url="https://service.test", api_key="test_retry_key") as client:
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(send))
        with pytest.raises(SmartMemoryClientError) as caught:
            call(client)
    assert len(committed) == 1
    assert caught.value.attempts == 1
    assert caught.value.idempotency_key == "test_retry_key"
    assert caught.value.status_code == (None if failure == "read_timeout" else failure)


@pytest.mark.parametrize("name,call", CALLS, ids=[r[0] for r in CALLS])
@pytest.mark.parametrize("failure", [429, "connect_error", "connect_timeout"])
def test_pre_send_refusal_retries_identical_bytes(name, call, failure):
    sent = []
    def send(request):
        sent.append(request.content)
        if len(sent) == 1:
            if failure == "connect_error":
                raise httpx.ConnectError("test_retry: refused", request=request)
            if failure == "connect_timeout":
                raise httpx.ConnectTimeout("test_retry: connect timeout", request=request)
            return httpx.Response(429, json={}, request=request)
        return httpx.Response(200, json=FIXTURE, request=request)
    with SmartMemoryClient(base_url="https://service.test", api_key="test_retry_key") as client:
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(send))
        assert call(client).run_id == "run_1"
    assert len(sent) == 2
    assert sent[0] == sent[1]
    assert json.loads(sent[0])["idempotency_key"] == "test_retry_key"


@pytest.mark.parametrize("name,call", CALLS, ids=[r[0] for r in CALLS])
@pytest.mark.parametrize("failure", [429, "connect_error", "connect_timeout"])
@pytest.mark.parametrize("field", ["workspace_id", "_api_key", "_token", "base_url"])
def test_changed_scope_refuses_retry_before_send(name, call, failure, field):
    from smartmemory_client import errors

    sent = []
    with SmartMemoryClient(
        base_url="https://service.test", api_key="test_retry_auth", workspace_id="test_retry_A"
    ) as client:
        def send(request):
            sent.append(request)
            if len(sent) > 1:
                return httpx.Response(200, json=FIXTURE, request=request)
            setattr(client, field, "https://changed.test" if field == "base_url" else "test_retry_B")
            if failure == "connect_error":
                raise httpx.ConnectError("test_retry: refused", request=request)
            if failure == "connect_timeout":
                raise httpx.ConnectTimeout("test_retry: connect timeout", request=request)
            return httpx.Response(429, json={}, request=request)

        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(send))
        with pytest.raises(SmartMemoryClientError) as caught:
            call(client)
    assert isinstance(caught.value, errors.SubmitScopeChangedError)
    assert caught.value.code == "submit_scope_changed"
    assert caught.value.attempts == 1
    assert caught.value.idempotency_key == "test_retry_key"
    assert len(sent) == 1
    assert sent[0].url.host == "service.test"
    assert sent[0].headers["X-Workspace-Id"] == "test_retry_A"
    assert sent[0].headers["Authorization"] == "Bearer test_retry_auth"
    assert json.loads(sent[0].content)["idempotency_key"] == "test_retry_key"
    assert "test_retry_auth" not in str(caught.value)
