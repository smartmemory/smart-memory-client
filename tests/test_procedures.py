"""Tests for procedure catalog SDK methods (CFS-3).

Covers happy path and HTTP error codes for list_procedures() and get_procedure().
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


class TestListProcedures:
    """Tests for list_procedures()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "total_count": 2,
            "procedures": [
                {
                    "id": "proc-1",
                    "name": "Login Flow",
                    "description": "Standard login procedure",
                    "created_at": "2026-02-01T00:00:00Z",
                    "match_stats": {
                        "total_matches": 10,
                        "successful": 8,
                        "failed": 1,
                        "neutral": 1,
                        "no_feedback": 0,
                        "avg_confidence": 0.92,
                        "success_rate": 0.8,
                        "total_tokens_saved": 0,
                    },
                },
                {
                    "id": "proc-2",
                    "name": "Search Query",
                    "description": "Search flow handler",
                    "created_at": "2026-02-02T00:00:00Z",
                    "match_stats": {
                        "total_matches": 5,
                        "successful": 5,
                        "failed": 0,
                        "neutral": 0,
                        "no_feedback": 0,
                        "avg_confidence": 0.95,
                        "success_rate": 1.0,
                        "total_tokens_saved": 0,
                    },
                },
            ],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.list_procedures()
        assert result == expected
        assert result["total_count"] == 2
        assert len(result["procedures"]) == 2
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_with_all_params(self, mock_request, client):
        mock_request.return_value = _ok_response({"procedures": [], "total_count": 0})

        client.list_procedures(
            limit=25,
            offset=10,
            sort_by="success_rate",
            sort_order="asc",
        )

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["limit"] == 25
        assert params["offset"] == 10
        assert params["sort_by"] == "success_rate"
        assert params["sort_order"] == "asc"

    @patch("httpx.Client.request")
    def test_uses_defaults(self, mock_request, client):
        mock_request.return_value = _ok_response({"procedures": [], "total_count": 0})

        client.list_procedures()

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["limit"] == 50
        assert params["offset"] == 0
        assert params["sort_order"] == "desc"
        assert "sort_by" not in params  # None values should be omitted

    @patch("httpx.Client.request")
    def test_omits_none_sort_by(self, mock_request, client):
        mock_request.return_value = _ok_response({"procedures": [], "total_count": 0})

        client.list_procedures(sort_by=None)

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "sort_by" not in params

    @patch("httpx.Client.request")
    def test_400_raises_error(self, mock_request, client):
        """400 returned when sort_by is invalid."""
        mock_request.return_value = _error_response(400, "Invalid sort_by value")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedures(sort_by="invalid_field")

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedures()


class TestGetProcedure:
    """Tests for get_procedure()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "id": "proc-1",
            "name": "Login Flow",
            "description": "Standard login procedure",
            "content": "When user requests login, verify credentials...",
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-05T00:00:00Z",
            "metadata": {"source": "manual"},
            "match_stats": {
                "total_matches": 10,
                "successful": 8,
                "failed": 1,
                "neutral": 1,
                "no_feedback": 0,
                "avg_confidence": 0.92,
                "success_rate": 0.8,
                "total_tokens_saved": 0,
            },
            "recent_matches": [
                {
                    "match_id": "m-1",
                    "timestamp": "2026-02-10T10:00:00Z",
                    "confidence": 0.95,
                    "feedback": "success",
                }
            ],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.get_procedure("proc-1")
        assert result == expected
        assert result["id"] == "proc-1"
        assert "recent_matches" in result
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_with_include_matches_true(self, mock_request, client):
        mock_request.return_value = _ok_response({"id": "proc-1", "recent_matches": []})

        client.get_procedure("proc-1", include_matches=True, match_limit=50)

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["include_matches"] is True
        assert params["match_limit"] == 50

    @patch("httpx.Client.request")
    def test_with_include_matches_false(self, mock_request, client):
        mock_request.return_value = _ok_response({"id": "proc-1"})

        client.get_procedure("proc-1", include_matches=False)

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["include_matches"] is False

    @patch("httpx.Client.request")
    def test_uses_defaults(self, mock_request, client):
        mock_request.return_value = _ok_response({"id": "proc-1", "recent_matches": []})

        client.get_procedure("proc-1")

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["include_matches"] is True
        assert params["match_limit"] == 20

    @patch("httpx.Client.request")
    def test_404_raises_error(self, mock_request, client):
        """404 returned when procedure does not exist."""
        mock_request.return_value = _error_response(
            404, "Procedure 'nonexistent' not found"
        )

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure("nonexistent")

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure("proc-1")
