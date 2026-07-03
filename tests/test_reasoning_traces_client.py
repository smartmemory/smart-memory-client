"""URL + error-propagation tests for the reasoning-traces client methods and
get_neighbors.

Regression guard for CODE_REVIEW_2026-07-02 (smart-memory-client):
  - The 4 reasoning-trace methods hit ``/memory/reasoning-traces/*`` (hyphen), but
    the service router prefix is ``/reasoning/traces`` → real path
    ``/memory/reasoning/traces/*`` (slash). Every call 404'd. The existing tests
    mocked the transport WITHOUT asserting the URL, so the drift shipped. These
    tests assert the ACTUAL request URL so a path regression fails loudly.
  - get_neighbors did ``except Exception: return []``, masking 404/403/500 as
    "no neighbors". It must propagate errors like every other method.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryServerError

BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc123"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _ok(json_data: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = ""
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data
    return resp


def _error(status_code: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = "boom"
    request = MagicMock(spec=httpx.Request)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status_code} Error", request=request, response=resp
    )
    return resp


def _called_url(mock_request: MagicMock) -> str:
    """httpx.request(method, url, ...) — url is the 2nd positional arg."""
    args = mock_request.call_args.args
    return args[1]


def _called_method(mock_request: MagicMock) -> str:
    return mock_request.call_args.args[0]


class TestReasoningTraceURLs:
    """Every reasoning-trace method must hit /memory/reasoning/traces/* (slash)."""

    @patch("httpx.Client.request")
    def test_extract_reasoning_url(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _ok({"has_reasoning": True})
        client.extract_reasoning("Thought: x. Conclusion: y.")
        assert _called_method(mock_request) == "POST"
        assert (
            _called_url(mock_request) == f"{BASE_URL}/memory/reasoning/traces/extract"
        )

    @patch("httpx.Client.request")
    def test_store_reasoning_trace_url(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _ok({"trace_id": "t1"})
        client.store_reasoning_trace({"trace_id": "t1", "steps": []})
        assert _called_method(mock_request) == "POST"
        assert _called_url(mock_request) == f"{BASE_URL}/memory/reasoning/traces/store"

    @patch("httpx.Client.request")
    def test_query_reasoning_url(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _ok({"results": []})
        client.query_reasoning("why did I choose python?")
        assert _called_method(mock_request) == "POST"
        assert _called_url(mock_request) == f"{BASE_URL}/memory/reasoning/traces/query"

    @patch("httpx.Client.request")
    def test_get_reasoning_trace_url(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _ok({"trace_id": "abc"})
        client.get_reasoning_trace("abc")
        assert _called_method(mock_request) == "GET"
        assert _called_url(mock_request) == f"{BASE_URL}/memory/reasoning/traces/abc"


class TestGetNeighborsPropagatesErrors:
    """get_neighbors must NOT swallow backend errors into []."""

    @patch("httpx.Client.request")
    def test_server_error_propagates(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _error(500)
        with pytest.raises(SmartMemoryServerError):
            client.get_neighbors("item-1")

    @patch("httpx.Client.request")
    def test_success_returns_neighbors(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _ok({"neighbors": [{"item_id": "n1"}]})
        assert client.get_neighbors("item-1") == [{"item_id": "n1"}]
