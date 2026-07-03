"""Tests for procedure evolution SDK methods (CFS-3b)."""

import pytest
from unittest.mock import MagicMock, patch

import httpx

from smartmemory_client import SmartMemoryClient, SmartMemoryClientError


@pytest.fixture
def client():
    """Create a test client with API key."""
    return SmartMemoryClient(
        base_url="http://test-server:9001",
        api_key="test-key",
    )


class TestGetProcedureEvolution:
    """Tests for get_procedure_evolution method."""

    @patch("httpx.Client.request")
    def test_get_procedure_evolution_success(self, mock_request, client):
        """Test successful evolution history retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "procedure_id": "proc_123",
            "current_version": 3,
            "total_events": 3,
            "events": [
                {
                    "event_id": "evt_001",
                    "event_type": "created",
                    "version": 1,
                    "timestamp": "2026-01-15T10:00:00Z",
                    "source_type": "working_memory",
                    "pattern_count": 5,
                    "confidence_at_event": 0.78,
                    "summary": "Promoted from working memory",
                }
            ],
        }
        mock_request.return_value = mock_response

        result = client.get_procedure_evolution("proc_123")

        assert result["procedure_id"] == "proc_123"
        assert result["current_version"] == 3
        assert result["total_events"] == 3
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == "created"

        # Verify request
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        # httpx.request(method, url, ...) - positional args
        assert call_args[0][0] == "GET"
        assert "/memory/procedures/proc_123/evolution" in call_args[0][1]

    @patch("httpx.Client.request")
    def test_get_procedure_evolution_with_pagination(self, mock_request, client):
        """Test evolution history with pagination parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "procedure_id": "proc_123",
            "current_version": 10,
            "total_events": 10,
            "events": [],
        }
        mock_request.return_value = mock_response

        client.get_procedure_evolution("proc_123", limit=5, offset=5)

        # Verify pagination params
        call_args = mock_request.call_args
        assert call_args[1]["params"]["limit"] == 5
        assert call_args[1]["params"]["offset"] == 5

    @patch("httpx.Client.request")
    def test_get_procedure_evolution_not_found(self, mock_request, client):
        """Test 404 error for non-existent procedure."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Procedure 'proc_999' not found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )
        mock_request.return_value = mock_response

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_evolution("proc_999")


class TestGetProcedureEvolutionEvent:
    """Tests for get_procedure_evolution_event method."""

    @patch("httpx.Client.request")
    def test_get_evolution_event_success(self, mock_request, client):
        """Test successful single event retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "event_id": "evt_001",
            "event_type": "refined",
            "version": 2,
            "timestamp": "2026-01-16T10:00:00Z",
            "source_type": "working_memory",
            "pattern_count": 8,
            "confidence_at_event": 0.85,
            "summary": "Procedure refined",
            "content_snapshot": {
                "content": "Test procedure content",
                "name": "Test Procedure",
                "skills": ["skill1", "skill2"],
                "tools": ["tool1"],
                "steps": ["step1", "step2"],
            },
            "source": {
                "type": "working_memory",
                "source_items": [],
                "pattern_count": 8,
            },
            "match_stats_at_event": {
                "total_matches": 10,
                "success_rate": 0.9,
            },
            "changes_from_previous": {
                "has_changes": True,
                "summary": "+1 skills; content modified",
                "diff": {"skills": {"added": ["skill2"], "removed": []}},
            },
        }
        mock_request.return_value = mock_response

        result = client.get_procedure_evolution_event("proc_123", "evt_001")

        assert result["event_id"] == "evt_001"
        assert result["event_type"] == "refined"
        assert result["version"] == 2
        assert result["content_snapshot"]["content"] == "Test procedure content"
        assert result["changes_from_previous"]["has_changes"] is True

        # Verify request
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert "/memory/procedures/proc_123/evolution/evt_001" in call_args[0][1]

    @patch("httpx.Client.request")
    def test_get_evolution_event_not_found(self, mock_request, client):
        """Test 404 error for non-existent event."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Evolution event 'evt_999' not found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )
        mock_request.return_value = mock_response

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_evolution_event("proc_123", "evt_999")


class TestGetProcedureConfidenceTrajectory:
    """Tests for get_procedure_confidence_trajectory method."""

    @patch("httpx.Client.request")
    def test_get_confidence_trajectory_success(self, mock_request, client):
        """Test successful confidence trajectory retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "procedure_id": "proc_123",
            "data_points": [
                {
                    "timestamp": "2026-01-15T10:00:00",
                    "confidence": 0.78,
                    "matches": 5,
                    "success_rate": 0.80,
                    "event_type": "created",
                    "version": 1,
                },
                {
                    "timestamp": "2026-01-16T10:00:00",
                    "confidence": 0.82,
                    "matches": 10,
                    "success_rate": 0.85,
                    "event_type": "refined",
                    "version": 2,
                },
                {
                    "timestamp": "2026-01-17T10:00:00",
                    "confidence": 0.90,
                    "matches": 20,
                    "success_rate": 0.90,
                    "event_type": "refined",
                    "version": 3,
                },
            ],
        }
        mock_request.return_value = mock_response

        result = client.get_procedure_confidence_trajectory("proc_123")

        assert result["procedure_id"] == "proc_123"
        assert len(result["data_points"]) == 3
        # Verify data points are in chronological order with increasing confidence
        assert result["data_points"][0]["confidence"] == 0.78
        assert result["data_points"][2]["confidence"] == 0.90

        # Verify request
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert "/memory/procedures/proc_123/confidence-trajectory" in call_args[0][1]

    @patch("httpx.Client.request")
    def test_get_confidence_trajectory_empty(self, mock_request, client):
        """Test trajectory for procedure with no events."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "procedure_id": "proc_new",
            "data_points": [],
        }
        mock_request.return_value = mock_response

        result = client.get_procedure_confidence_trajectory("proc_new")

        assert result["procedure_id"] == "proc_new"
        assert result["data_points"] == []

    @patch("httpx.Client.request")
    def test_get_confidence_trajectory_not_found(self, mock_request, client):
        """Test 404 error for non-existent procedure."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Procedure 'proc_999' not found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )
        mock_request.return_value = mock_response

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_confidence_trajectory("proc_999")


class TestErrorHandling:
    """Tests for error handling across evolution methods."""

    @patch("httpx.Client.request")
    def test_server_error_500(self, mock_request, client):
        """Test 500 server error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_response
        )
        mock_request.return_value = mock_response

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_evolution("proc_123")

    @patch("httpx.Client.request")
    def test_bad_request_400(self, mock_request, client):
        """Test 400 bad request handling."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid limit parameter"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=mock_response
        )
        mock_request.return_value = mock_response

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_procedure_evolution("proc_123", limit=-1)
