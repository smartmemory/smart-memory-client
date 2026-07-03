"""Tests for procedure candidates SDK methods (CFS-3b).

Covers happy path and HTTP error codes for:
- list_procedure_candidates()
- promote_procedure_candidate()
- dismiss_procedure_candidate()

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


# ============================================================================
# list_procedure_candidates() Tests
# ============================================================================


class TestListProcedureCandidates:
    """Tests for list_procedure_candidates()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "candidate_count": 2,
            "total_working_items": 50,
            "candidates": [
                {
                    "cluster_id": "cluster-1",
                    "suggested_name": "API Error Handling Pattern",
                    "suggested_description": "Pattern detected in 5 similar items involving error_handling.",
                    "representative_content": "When receiving a 401 error from the API...",
                    "item_count": 5,
                    "scores": {
                        "recommendation_score": 0.85,
                        "frequency_score": 0.8,
                        "consistency_score": 0.9,
                        "recency_score": 0.75,
                        "agent_workflow_score": 0.7,
                    },
                    "common_skills": ["error_handling", "auth"],
                    "common_tools": ["api_client"],
                    "sample_item_ids": ["id1", "id2", "id3"],
                    "date_range": {
                        "earliest": "2026-02-01T00:00:00+00:00",
                        "latest": "2026-02-10T00:00:00+00:00",
                    },
                },
                {
                    "cluster_id": "cluster-2",
                    "suggested_name": "Data Validation Pattern",
                    "suggested_description": "Pattern detected in 4 similar items involving validation.",
                    "representative_content": "Validate user input before...",
                    "item_count": 4,
                    "scores": {
                        "recommendation_score": 0.72,
                        "frequency_score": 0.6,
                        "consistency_score": 0.85,
                        "recency_score": 0.8,
                        "agent_workflow_score": 0.5,
                    },
                    "common_skills": ["validation"],
                    "common_tools": ["database"],
                    "sample_item_ids": ["id4", "id5"],
                    "date_range": {
                        "earliest": "2026-02-05T00:00:00+00:00",
                        "latest": "2026-02-11T00:00:00+00:00",
                    },
                },
            ],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.list_procedure_candidates()
        assert result == expected
        assert result["candidate_count"] == 2
        assert len(result["candidates"]) == 2
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_with_all_params(self, mock_request, client):
        mock_request.return_value = _ok_response(
            {"candidates": [], "candidate_count": 0}
        )

        client.list_procedure_candidates(
            min_score=0.8,
            min_cluster_size=5,
            days_back=14,
            limit=10,
        )

        mock_request.assert_called_once()
        _, kwargs = mock_request.call_args
        assert kwargs["params"]["min_score"] == 0.8
        assert kwargs["params"]["min_cluster_size"] == 5
        assert kwargs["params"]["days_back"] == 14
        assert kwargs["params"]["limit"] == 10

    @patch("httpx.Client.request")
    def test_empty_candidates(self, mock_request, client):
        expected = {
            "workspace_id": "ws-1",
            "candidate_count": 0,
            "total_working_items": 10,
            "candidates": [],
        }
        mock_request.return_value = _ok_response(expected)

        result = client.list_procedure_candidates()
        assert result["candidate_count"] == 0
        assert result["candidates"] == []

    @patch("httpx.Client.request")
    def test_404_not_found(self, mock_request, client):
        mock_request.return_value = _error_response(404, "Not found")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedure_candidates()

    @patch("httpx.Client.request")
    def test_400_bad_request(self, mock_request, client):
        """Test 400 error for invalid parameters."""
        mock_request.return_value = _error_response(400, "Invalid min_score value")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedure_candidates(min_score=-1.0)

    @patch("httpx.Client.request")
    def test_500_server_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal server error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_procedure_candidates()


# ============================================================================
# promote_procedure_candidate() Tests
# ============================================================================


class TestPromoteProcedureCandidate:
    """Tests for promote_procedure_candidate()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "status": "success",
            "procedure_id": "proc-new-123",
            "name": "API Error Handler",
            "items_promoted": 5,
            "items_removed": 0,
        }
        mock_request.return_value = _ok_response(expected)

        result = client.promote_procedure_candidate(
            cluster_id="cluster-1",
            name="API Error Handler",
            description="Handles 401 errors from external APIs",
        )

        assert result == expected
        assert result["status"] == "success"
        assert result["procedure_id"] == "proc-new-123"
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_minimal_params(self, mock_request, client):
        expected = {
            "status": "success",
            "procedure_id": "proc-456",
            "name": "Auto-generated Name",
            "items_promoted": 3,
            "items_removed": 0,
        }
        mock_request.return_value = _ok_response(expected)

        result = client.promote_procedure_candidate(cluster_id="cluster-2")

        assert result["status"] == "success"
        mock_request.assert_called_once()
        _, kwargs = mock_request.call_args
        body = kwargs["json"]
        assert body["name"] is None  # Uses suggested_name
        assert body["description"] is None
        assert body["procedure_type"] == "extraction"
        assert body["preferred_profile"] == "quick_extract"
        assert body["remove_working_items"] is False

    @patch("httpx.Client.request")
    def test_with_remove_working_items(self, mock_request, client):
        expected = {
            "status": "success",
            "procedure_id": "proc-789",
            "name": "Test Proc",
            "items_promoted": 5,
            "items_removed": 5,
        }
        mock_request.return_value = _ok_response(expected)

        result = client.promote_procedure_candidate(
            cluster_id="cluster-3",
            remove_working_items=True,
        )

        assert result["items_removed"] == 5

    @patch("httpx.Client.request")
    def test_404_cluster_not_found(self, mock_request, client):
        mock_request.return_value = _error_response(404, "Candidate cluster not found")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.promote_procedure_candidate(cluster_id="nonexistent")

    @patch("httpx.Client.request")
    def test_400_dismissed_cluster(self, mock_request, client):
        mock_request.return_value = _error_response(
            400, "Cannot promote a dismissed candidate"
        )

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.promote_procedure_candidate(cluster_id="dismissed-cluster")

    @patch("httpx.Client.request")
    def test_500_server_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Internal server error")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.promote_procedure_candidate(cluster_id="cluster-1")


# ============================================================================
# dismiss_procedure_candidate() Tests
# ============================================================================


class TestDismissProcedureCandidate:
    """Tests for dismiss_procedure_candidate()."""

    @patch("httpx.Client.request")
    def test_happy_path(self, mock_request, client):
        expected = {
            "status": "success",
            "cluster_id": "cluster-1",
            "message": "Candidate dismissed from future recommendations",
        }
        mock_request.return_value = _ok_response(expected)

        result = client.dismiss_procedure_candidate(cluster_id="cluster-1")

        assert result == expected
        assert result["status"] == "success"
        mock_request.assert_called_once()

    @patch("httpx.Client.request")
    def test_already_dismissed(self, mock_request, client):
        expected = {
            "status": "success",
            "cluster_id": "cluster-2",
            "message": "Candidate was already dismissed",
        }
        mock_request.return_value = _ok_response(expected)

        result = client.dismiss_procedure_candidate(cluster_id="cluster-2")

        assert result["message"] == "Candidate was already dismissed"

    @patch("httpx.Client.request")
    def test_500_server_error(self, mock_request, client):
        mock_request.return_value = _error_response(500, "Failed to dismiss candidate")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.dismiss_procedure_candidate(cluster_id="cluster-1")
