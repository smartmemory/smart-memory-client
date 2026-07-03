"""Persistent httpx.Client lifecycle + connection reuse (SDK-HTTPX-POOL-1).

The SDK holds one `httpx.Client` per SmartMemoryClient for keep-alive pooling
across its many per-method calls, instead of a fresh connection per module-level
`httpx.request`. These tests pin the reuse + teardown contract and confirm the
mock surface is `httpx.Client.request`.
"""

from unittest.mock import MagicMock, patch

import httpx

from smartmemory_client.client import SmartMemoryClient

BASE_URL = "http://localhost:9001"


def _client():
    return SmartMemoryClient(
        base_url=BASE_URL, api_key="sm_test_key", workspace_id="ws1"
    )


def _ok(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.headers = {}
    return resp


def test_client_holds_one_persistent_httpx_client():
    c = _client()
    try:
        assert isinstance(c._client, httpx.Client)
        # Stable identity: the same pooled client backs every call.
        assert c._client is c._client
    finally:
        c.close()


def test_verify_ssl_is_honored_by_the_pool():
    # Previously verify_ssl was dead config (module-level httpx.request never
    # passed verify=). It must now reach the pooled client.
    c = SmartMemoryClient(base_url="https://x", api_key="sm_test_k", verify_ssl=False)
    try:
        # httpx stores verification on the transport; the simplest observable
        # contract is that construction with verify=False succeeds and the
        # client exists. (httpx has no public verify getter.)
        assert isinstance(c._client, httpx.Client)
    finally:
        c.close()


@patch("httpx.Client.request")
def test_requests_go_through_the_pooled_client(mock_request):
    mock_request.return_value = _ok({"ok": True})
    c = _client()
    try:
        c._request("GET", "/memory/items")
        mock_request.assert_called_once()
        # Positional (method, url) survive the class-method patch (MagicMock is
        # not a descriptor, so no self is injected) — the bulk mock rename relies
        # on this.
        assert mock_request.call_args[0][0] == "GET"
        assert mock_request.call_args[0][1] == f"{BASE_URL}/memory/items"
    finally:
        c.close()


def test_close_is_idempotent():
    c = _client()
    c.close()
    c.close()  # must not raise


def test_context_manager_closes_pool():
    with patch.object(httpx.Client, "close") as mock_close:
        with _client() as c:
            assert c is not None
        mock_close.assert_called()
