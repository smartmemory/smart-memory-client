"""Tests for Decision Memory client SDK methods."""

from unittest.mock import MagicMock, patch

import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError


@pytest.fixture
def client():
    """Create a client with a mock API key."""
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


@pytest.fixture
def mock_response():
    """Helper to create mock httpx responses."""

    def _make(json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    return _make


class TestCreateDecision:
    @patch("smartmemory_client.client.httpx.request")
    def test_create_decision_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_123",
                "content": "Python is best for ML",
                "decision_type": "inference",
                "confidence": 0.8,
                "status": "created",
            }
        )

        result = client.create_decision("Python is best for ML")
        assert result["decision_id"] == "dec_123"
        assert result["status"] == "created"

        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["json"]["content"] == "Python is best for ML"
        assert call_kwargs[1]["json"]["decision_type"] == "inference"

    @patch("smartmemory_client.client.httpx.request")
    def test_create_decision_with_options(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_456",
                "content": "Use React",
                "confidence": 0.9,
                "status": "created",
            }
        )

        result = client.create_decision(
            "Use React",
            decision_type="preference",
            confidence=0.9,
            domain="frontend",
            tags=["framework", "ui"],
            evidence_ids=["mem_1", "mem_2"],
        )
        assert result["decision_id"] == "dec_456"

        body = mock_req.call_args[1]["json"]
        assert body["decision_type"] == "preference"
        assert body["confidence"] == 0.9
        assert body["domain"] == "frontend"
        assert body["tags"] == ["framework", "ui"]
        assert body["evidence_ids"] == ["mem_1", "mem_2"]

    @patch("smartmemory_client.client.httpx.request")
    def test_create_decision_with_expertise_fields(self, mock_req, client, mock_response):
        """CORE-EXPERTISE-1 Phase 1 — rejected_alternatives, rationale, constraints
        flow into the request payload AND back out of the response into the caller.
        """
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_exp",
                "content": "Use JWT",
                "status": "active",
                "rejected_alternatives": ["session tokens", "OAuth"],
                "rationale": "Stateless plus mobile coverage",
                "constraints": ["mobile <v3.2", "no shared store"],
            }
        )

        result = client.create_decision(
            "Use JWT",
            decision_type="choice",
            rejected_alternatives=["session tokens", "OAuth"],
            rationale="Stateless plus mobile coverage",
            constraints=["mobile <v3.2", "no shared store"],
        )

        # Outbound: payload contains the snake_case keys.
        body = mock_req.call_args[1]["json"]
        assert body["rejected_alternatives"] == ["session tokens", "OAuth"]
        assert body["rationale"] == "Stateless plus mobile coverage"
        assert body["constraints"] == ["mobile <v3.2", "no shared store"]

        # Inbound: response surfaces the three fields back to the caller.
        assert result["rejected_alternatives"] == ["session tokens", "OAuth"]
        assert result["rationale"] == "Stateless plus mobile coverage"
        assert result["constraints"] == ["mobile <v3.2", "no shared store"]

    @patch("smartmemory_client.client.httpx.request")
    def test_get_decision_surfaces_expertise_fields(self, mock_req, client, mock_response):
        """get_decision() must surface the three new fields back to the caller."""
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_exp",
                "content": "Use JWT",
                "status": "active",
                "rejected_alternatives": ["session tokens"],
                "rationale": "Stateless",
                "constraints": ["mobile <v3.2"],
            }
        )
        result = client.get_decision("dec_exp")
        assert result["rejected_alternatives"] == ["session tokens"]
        assert result["rationale"] == "Stateless"
        assert result["constraints"] == ["mobile <v3.2"]

    @patch("smartmemory_client.client.httpx.request")
    def test_create_decision_omits_expertise_fields_when_unset(self, mock_req, client, mock_response):
        """Backward-compat: omitting the new kwargs leaves them out of the payload."""
        mock_req.return_value = mock_response(
            {"decision_id": "dec_old", "content": "Pre-expertise", "status": "active"}
        )

        client.create_decision("Pre-expertise")

        body = mock_req.call_args[1]["json"]
        assert "rejected_alternatives" not in body
        assert "rationale" not in body
        assert "constraints" not in body


class TestGetDecision:
    @patch("smartmemory_client.client.httpx.request")
    def test_get_decision(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_123",
                "content": "Use PostgreSQL",
                "status": "active",
                "confidence": 0.85,
            }
        )

        result = client.get_decision("dec_123")
        assert result["decision_id"] == "dec_123"
        assert "memory/decisions/dec_123" in mock_req.call_args[0][1]


class TestListDecisions:
    @patch("smartmemory_client.client.httpx.request")
    def test_list_decisions_default(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decisions": [{"decision_id": "dec_1"}, {"decision_id": "dec_2"}],
                "count": 2,
            }
        )

        result = client.list_decisions()
        assert len(result) == 2

    @patch("smartmemory_client.client.httpx.request")
    def test_list_decisions_with_filters(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"decisions": [], "count": 0})

        client.list_decisions(
            domain="backend", decision_type="inference", min_confidence=0.5, limit=10
        )
        params = mock_req.call_args[1]["params"]
        assert params["domain"] == "backend"
        assert params["decision_type"] == "inference"
        assert params["min_confidence"] == 0.5
        assert params["limit"] == 10


class TestSupersedeDecision:
    @patch("smartmemory_client.client.httpx.request")
    def test_supersede_decision(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "old_decision_id": "dec_old",
                "new_decision_id": "dec_new",
                "status": "superseded",
            }
        )

        result = client.supersede_decision(
            "dec_old", "New approach", "Better data available"
        )
        assert result["status"] == "superseded"
        assert result["new_decision_id"] == "dec_new"

        body = mock_req.call_args[1]["json"]
        assert body["new_content"] == "New approach"
        assert body["reason"] == "Better data available"


class TestRetractDecision:
    @patch("smartmemory_client.client.httpx.request")
    def test_retract_decision(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_123",
                "status": "retracted",
            }
        )

        result = client.retract_decision("dec_123", "No longer valid")
        assert result["status"] == "retracted"
        body = mock_req.call_args[1]["json"]
        assert body["reason"] == "No longer valid"


class TestReinforceDecision:
    @patch("smartmemory_client.client.httpx.request")
    def test_reinforce_decision(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision_id": "dec_123",
                "confidence": 0.88,
                "reinforcement_count": 3,
            }
        )

        result = client.reinforce_decision("dec_123", "mem_evidence_42")
        assert result["confidence"] == 0.88
        assert result["reinforcement_count"] == 3
        body = mock_req.call_args[1]["json"]
        assert body["evidence_id"] == "mem_evidence_42"


class TestProvenanceChain:
    @patch("smartmemory_client.client.httpx.request")
    def test_get_provenance_chain(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision": {"decision_id": "dec_123"},
                "reasoning_trace": {"trace_id": "trace_1"},
                "evidence": [{"item_id": "mem_1"}],
                "superseded": [],
            }
        )

        result = client.get_provenance_chain("dec_123")
        assert result["decision"]["decision_id"] == "dec_123"
        assert len(result["evidence"]) == 1


class TestCausalChain:
    @patch("smartmemory_client.client.httpx.request")
    def test_get_causal_chain(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "decision": {"decision_id": "dec_123"},
                "causes": [{"decision_id": "dec_prior"}],
                "effects": [],
            }
        )

        result = client.get_causal_chain("dec_123", direction="causes", max_depth=5)
        assert len(result["causes"]) == 1
        params = mock_req.call_args[1]["params"]
        assert params["direction"] == "causes"
        assert params["max_depth"] == 5


class TestErrorHandling:
    @patch("smartmemory_client.client.httpx.request")
    def test_decision_not_found(self, mock_req, client):
        import httpx

        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Decision not found"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=resp
        )
        mock_req.return_value = resp

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_decision("nonexistent")

    @patch("smartmemory_client.client.httpx.request")
    def test_decision_bad_request(self, mock_req, client):
        import httpx

        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Validation error"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=resp
        )
        mock_req.return_value = resp

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.create_decision("")

    @patch("smartmemory_client.client.httpx.request")
    def test_decision_server_error(self, mock_req, client):
        import httpx

        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal server error"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp
        )
        mock_req.return_value = resp

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_decisions()
