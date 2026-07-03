"""Tests for token usage SDK methods (CFS-1).

Covers happy path and HTTP error codes for get_token_usage() and get_token_usage_current().
All HTTP calls are mocked so no running server is required.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError

BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc123"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _ok_response(json_data: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = ""
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data
    return resp


def _error_response(status_code: int, body: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    request = MagicMock(spec=httpx.Request)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status_code} Error",
        request=request,
        response=resp,
    )
    resp.json.return_value = {}
    return resp


class TestGetTokenUsage:
    """Tests for get_token_usage()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "record_count": 2,
            "total_spent": 1500,
            "total_avoided": 800,
            "savings_pct": 34.8,
            "records": [],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.get_token_usage()
        assert result == expected
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_with_params(self, mock_request, client):
        mock_request.return_value = _ok_response({"records": []})

        client.get_token_usage(
            start_date="2026-02-01",
            end_date="2026-02-11",
            group_by="stage",
            limit=50,
        )

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["start_date"] == "2026-02-01"
        assert params["end_date"] == "2026-02-11"
        assert params["group_by"] == "stage"
        assert params["limit"] == 50

    @patch("httpx.Client.request")
    def test_omits_none_params(self, mock_request, client):
        mock_request.return_value = _ok_response({"records": []})

        client.get_token_usage()

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "start_date" not in params
        assert "end_date" not in params
        assert "group_by" not in params

    @patch("httpx.Client.request")
    def test_400_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(400, "Invalid start_date format")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_token_usage(start_date="bad-date")

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_token_usage()


class TestGetTokenUsageCurrent:
    """Tests for get_token_usage_current()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "cache_stats": {"hits": 100, "misses": 20},
            "recent_runs": [],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.get_token_usage_current()
        assert result == expected

    @patch("httpx.Client.request")
    def test_401_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(401, "Unauthorized")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_token_usage_current()

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_token_usage_current()
