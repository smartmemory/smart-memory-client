"""Tests for procedure match SDK methods (CFS-2).

Covers happy path and HTTP error codes for list_procedure_matches(),
submit_procedure_match_feedback(), and get_procedure_match_stats().
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


class TestListProcedureMatches:
    """Tests for list_procedure_matches()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "record_count": 0,
            "records": [],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.list_procedure_matches()
        assert result == expected
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_with_all_params(self, mock_request, client):
        mock_request.return_value = _ok_response({"records": []})

        client.list_procedure_matches(
            start_date="2026-02-01",
            end_date="2026-02-12",
            procedure_id="proc-1",
            feedback="success",
            limit=50,
        )

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["start_date"] == "2026-02-01"
        assert params["end_date"] == "2026-02-12"
        assert params["procedure_id"] == "proc-1"
        assert params["feedback"] == "success"
        assert params["limit"] == 50

    @patch("httpx.Client.request")
    def test_omits_none_params(self, mock_request, client):
        mock_request.return_value = _ok_response({"records": []})

        client.list_procedure_matches()

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "start_date" not in params
        assert "end_date" not in params
        assert "procedure_id" not in params
        assert "feedback" not in params

    @patch("httpx.Client.request")
    def test_400_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(400, "Invalid feedback value")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedure_matches(feedback="invalid")

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedure_matches()


class TestSubmitProcedureMatchFeedback:
    """Tests for submit_procedure_match_feedback()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {"status": "success", "match_id": "match-1", "feedback": "success"}
        mock_request.return_value = _ok_response(expected)

        result = client.submit_procedure_match_feedback("match-1", "success")
        assert result == expected

    @patch("httpx.Client.request")
    def test_with_note(self, mock_request, client):
        mock_request.return_value = _ok_response({"status": "success"})

        client.submit_procedure_match_feedback(
            "match-1", "failure", note="Wrong profile selected"
        )

        call_kwargs = mock_request.call_args
        json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        assert json_body["feedback"] == "failure"
        assert json_body["note"] == "Wrong profile selected"

    @patch("httpx.Client.request")
    def test_without_note(self, mock_request, client):
        mock_request.return_value = _ok_response({"status": "success"})

        client.submit_procedure_match_feedback("match-1", "neutral")

        call_kwargs = mock_request.call_args
        json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        assert json_body["feedback"] == "neutral"
        assert "note" not in json_body

    @patch("httpx.Client.request")
    def test_404_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(404, "Not found")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.submit_procedure_match_feedback("nonexistent", "success")

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.submit_procedure_match_feedback("match-1", "success")


class TestGetProcedureMatchStats:
    """Tests for get_procedure_match_stats()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "total_matches": 10,
            "successful": 7,
            "failed": 2,
            "neutral": 1,
            "no_feedback": 0,
            "avg_confidence": 0.91,
            "by_procedure": {},
        }
        mock_request.return_value = _ok_response(expected)

        result = client.get_procedure_match_stats()
        assert result == expected

    @patch("httpx.Client.request")
    def test_401_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(401, "Unauthorized")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_match_stats()

    @patch("httpx.Client.request")
    def test_500_raises_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_match_stats()
