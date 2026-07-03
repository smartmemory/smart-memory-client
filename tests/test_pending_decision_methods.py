"""Tests for Pending Decision lifecycle client SDK methods."""

from unittest.mock import MagicMock, patch

import pytest

from smartmemory_client.client import SmartMemoryClient


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


class TestPendingLifecycle:
    @patch("httpx.Client.request")
    def test_create_pending(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"decision_id": "dec_1", "status": "pending"})
        out = client.create_pending_decision(
            "case", [{"description": "x", "requirement_type": "proof"}], domain="gtm"
        )
        assert out["decision_id"] == "dec_1"
        args = mock_req.call_args
        assert args[0][0] == "POST"
        assert args[0][1] == "http://localhost:9001/memory/decisions/pending/create"
        body = args[1]["json"]
        assert body["content"] == "case"
        assert body["requirements"] == [{"description": "x", "requirement_type": "proof"}]
        assert body["domain"] == "gtm"

    @patch("httpx.Client.request")
    def test_resolve_requirement(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"resolved": True})
        client.resolve_requirement("dec_1", "req_1", "mem_1")
        args = mock_req.call_args
        assert args[0][1].endswith("/memory/decisions/pending/dec_1/resolve")
        assert args[1]["json"] == {"requirement_id": "req_1", "memory_id": "mem_1"}

    @patch("httpx.Client.request")
    def test_try_activate(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"activated": True})
        client.try_activate_decision("dec_1")
        args = mock_req.call_args
        assert args[0][1].endswith("/memory/decisions/pending/dec_1/activate")

    @patch("httpx.Client.request")
    def test_list_pending(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"decisions": [], "count": 0})
        client.list_pending_decisions(limit=10)
        args = mock_req.call_args
        assert args[0][1].endswith("/memory/decisions/pending")
        assert args[1]["params"] == {"limit": 10}
