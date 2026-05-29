"""Tests for evaluation SDK methods — CORE-AGENT-2 S03-T10.

Tests client.get_evaluation() and client.list_evaluation_history()
with mocked HTTP responses, mirroring test_decision_methods.py pattern.
"""

import httpx
from unittest.mock import MagicMock, patch

import pytest

from smartmemory_client.client import SmartMemoryClient
from smartmemory_client import SmartMemoryClientError, SmartMemoryNotFoundError


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# get_evaluation
# ---------------------------------------------------------------------------


class TestGetEvaluation:
    @patch("smartmemory_client.client.httpx.request")
    def test_get_evaluation_returns_dict(self, mock_req, client):
        """200 {evaluation: {...}} → returns the inner dict."""
        payload = {
            "evaluation": {
                "agent_id": "agent_abc",
                "dimension": "decision_volume",
                "domain": "python",
                "score": 0.75,
                "trend": "stable",
                "recorded_at": "2026-05-24T12:00:00+00:00",
            }
        }
        mock_req.return_value = _mock_response(payload)

        result = client.get_evaluation("agent_abc", "decision_volume", "python")

        assert result is not None
        assert result["evaluation"]["score"] == 0.75
        assert result["evaluation"]["dimension"] == "decision_volume"

        call = mock_req.call_args
        assert "/memory/agents/agent_abc/evaluation" in str(call)

    @patch("smartmemory_client.client.httpx.request")
    def test_get_evaluation_cold_start_returns_null_body(self, mock_req, client):
        """200 {evaluation: null} cold-start is returned as-is (dict with null)."""
        mock_req.return_value = _mock_response({"evaluation": None})

        result = client.get_evaluation("agent_new", "decision_volume", "python")
        # SDK returns the response body; null evaluation is a valid cold-start response
        assert result is not None
        assert result.get("evaluation") is None

    @patch("smartmemory_client.client.httpx.request")
    def test_get_evaluation_404_raises(self, mock_req, client):
        """404 from service raises SmartMemoryNotFoundError (or base client error)."""
        mock_req.return_value = _mock_response(
            {"detail": "AGENT_NOT_FOUND"}, status_code=404
        )

        with pytest.raises((SmartMemoryClientError, SmartMemoryNotFoundError)):
            client.get_evaluation("foreign_agent", "decision_volume", "python")

    @patch("smartmemory_client.client.httpx.request")
    def test_get_evaluation_passes_params(self, mock_req, client):
        """Verify dimension and domain are passed as query params."""
        mock_req.return_value = _mock_response({"evaluation": None})

        client.get_evaluation("agent_xyz", "reinforcement_balance", "kubernetes")

        call = mock_req.call_args
        # params dict should contain our query parameters
        params = call[1].get("params", {})
        assert params.get("dimension") == "reinforcement_balance"
        assert params.get("domain") == "kubernetes"


# ---------------------------------------------------------------------------
# list_evaluation_history
# ---------------------------------------------------------------------------


class TestListEvaluationHistory:
    @patch("smartmemory_client.client.httpx.request")
    def test_list_history_returns_list(self, mock_req, client):
        """200 {history: [...]} → returns the response dict."""
        payload = {
            "history": [
                {
                    "agent_id": "agent_abc",
                    "dimension": "decision_volume",
                    "domain": "python",
                    "score": 0.80,
                    "recorded_at": "2026-05-24T14:00:00+00:00",
                    "superseded": False,
                },
                {
                    "agent_id": "agent_abc",
                    "dimension": "decision_volume",
                    "domain": "python",
                    "score": 0.72,
                    "recorded_at": "2026-05-23T14:00:00+00:00",
                    "superseded": True,
                },
            ]
        }
        mock_req.return_value = _mock_response(payload)

        result = client.list_evaluation_history(
            "agent_abc", "decision_volume", "python"
        )
        assert "history" in result
        assert len(result["history"]) == 2

        call = mock_req.call_args
        assert "/memory/agents/agent_abc/evaluation/history" in str(call)

    @patch("smartmemory_client.client.httpx.request")
    def test_list_history_default_limit(self, mock_req, client):
        """Default limit of 20 is passed as query param."""
        mock_req.return_value = _mock_response({"history": []})

        client.list_evaluation_history("agent_abc", "decision_volume", "python")

        call = mock_req.call_args
        params = call[1].get("params", {})
        assert params.get("limit") == 20

    @patch("smartmemory_client.client.httpx.request")
    def test_list_history_custom_limit(self, mock_req, client):
        """Custom limit is forwarded."""
        mock_req.return_value = _mock_response({"history": []})

        client.list_evaluation_history(
            "agent_abc", "decision_volume", "python", limit=5
        )

        call = mock_req.call_args
        params = call[1].get("params", {})
        assert params.get("limit") == 5

    @patch("smartmemory_client.client.httpx.request")
    def test_list_history_404_raises(self, mock_req, client):
        """404 raises SmartMemoryClientError."""
        mock_req.return_value = _mock_response(
            {"detail": "AGENT_NOT_FOUND"}, status_code=404
        )

        with pytest.raises((SmartMemoryClientError, SmartMemoryNotFoundError)):
            client.list_evaluation_history("foreign_agent", "decision_volume", "python")
