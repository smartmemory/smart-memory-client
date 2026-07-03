"""Unit tests for CODE-DEV-3 — SmartMemoryClient.code_search() method.

Tests (per error-coverage.md):
- test_code_search_happy_path: 200 response with code entity list
- test_code_search_semantic_param_forwarded: semantic=True sent as query param
- test_code_search_filters_forwarded: entity_type and repo forwarded
- test_code_search_defaults: default limit=20, semantic=False
- test_code_search_not_found: 404 → SmartMemoryClientError
- test_code_search_bad_request: 400 → SmartMemoryClientError
- test_code_search_server_error: 500 → SmartMemoryClientError
"""

import pytest
from unittest.mock import patch, MagicMock

import httpx

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError


@pytest.fixture
def client():
    return SmartMemoryClient(api_key="test-key", base_url="http://test-url")


@pytest.fixture
def mock_request(client):
    with patch.object(client, "_request") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCodeSearchHappyPath:
    def test_code_search_happy_path(self, client, mock_request):
        """200 response returns list of code entity dicts."""
        mock_request.return_value = [
            {"item_id": "code::repo::app.py::auth", "name": "auth", "score": 0.95},
        ]

        result = client.code_search("authentication", semantic=True)

        assert len(result) == 1
        assert result[0]["name"] == "auth"
        mock_request.assert_called_once_with(
            "GET",
            "/memory/code/search",
            params={"query": "authentication", "limit": 20, "semantic": True},
        )

    def test_code_search_semantic_param_forwarded(self, client, mock_request):
        """semantic=True is forwarded as a query param."""
        mock_request.return_value = []

        client.code_search("auth", semantic=True)

        call_args = mock_request.call_args
        assert (
            call_args.kwargs.get("params", call_args[1].get("params", {}))["semantic"]
            is True
        )

    def test_code_search_non_semantic_default(self, client, mock_request):
        """Default semantic=False is forwarded."""
        mock_request.return_value = []

        client.code_search("auth")

        call_args = mock_request.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params["semantic"] is False

    def test_code_search_filters_forwarded(self, client, mock_request):
        """entity_type and repo forwarded when provided."""
        mock_request.return_value = []

        client.code_search("auth", entity_type="function", repo="my-repo", limit=50)

        call_args = mock_request.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert params["entity_type"] == "function"
        assert params["repo"] == "my-repo"
        assert params["limit"] == 50

    def test_code_search_omits_none_filters(self, client, mock_request):
        """entity_type and repo omitted from params when None."""
        mock_request.return_value = []

        client.code_search("auth")

        call_args = mock_request.call_args
        params = call_args.kwargs.get("params", call_args[1].get("params", {}))
        assert "entity_type" not in params
        assert "repo" not in params


# ---------------------------------------------------------------------------
# Error handling (per error-coverage.md)
# ---------------------------------------------------------------------------


class TestCodeSearchErrorHandling:
    @patch("httpx.Client.request")
    def test_code_search_not_found(self, mock_req, client):
        """404 → SmartMemoryClientError."""
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not found"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=resp
        )
        mock_req.return_value = resp

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.code_search("nonexistent")

    @patch("httpx.Client.request")
    def test_code_search_bad_request(self, mock_req, client):
        """400 → SmartMemoryClientError."""
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad request"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=resp
        )
        mock_req.return_value = resp

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.code_search("auth", entity_type="invalid_type")

    @patch("httpx.Client.request")
    def test_code_search_server_error(self, mock_req, client):
        """500 → SmartMemoryClientError."""
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal server error"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp
        )
        mock_req.return_value = resp

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.code_search("auth")
