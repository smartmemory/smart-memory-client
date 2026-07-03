"""Tests for ontology HITL queue client SDK methods (ONTO-HITL-CONSUMER-1)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)
from smartmemory_client.client import SmartMemoryClient


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


@pytest.fixture
def mock_response():
    def _make(json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    return _make


def _error_response(status_code, text="error"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status_code), request=MagicMock(), response=resp
    )
    return resp


class TestListOntologyHitl:
    @patch("httpx.Client.request")
    def test_list_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "items": [
                    {"id": "h1", "kind": "name_conflict_unresolvable", "status": "open"}
                ],
                "count": 1,
                "open_count": 1,
            }
        )
        result = client.list_ontology_hitl()
        assert result["count"] == 1
        assert result["items"][0]["id"] == "h1"
        call = mock_req.call_args
        assert call[1]["params"]["status"] == "open"
        assert call[1]["params"]["limit"] == 50
        assert "kind" not in call[1]["params"]  # omitted when None

    @patch("httpx.Client.request")
    def test_list_with_filters(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {"items": [], "count": 0, "open_count": 0}
        )
        client.list_ontology_hitl(status="resolved", kind="missing_in_graph", limit=10)
        params = mock_req.call_args[1]["params"]
        assert params == {"status": "resolved", "limit": 10, "kind": "missing_in_graph"}

    @patch("httpx.Client.request")
    def test_list_server_error(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryServerError) as exc:
            client.list_ontology_hitl()
        assert exc.value.status_code == 500


class TestResolveOntologyHitl:
    @patch("httpx.Client.request")
    def test_resolve_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "item": {
                    "id": "h1",
                    "status": "resolved",
                    "resolution_action": "accepted",
                }
            }
        )
        result = client.resolve_ontology_hitl("h1", "accepted", note="done")
        assert result["item"]["status"] == "resolved"
        body = mock_req.call_args[1]["json"]
        assert body["action"] == "accepted"
        assert body["note"] == "done"

    @patch("httpx.Client.request")
    def test_resolve_not_found(self, mock_req, client):
        mock_req.return_value = _error_response(404, "not found")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.resolve_ontology_hitl("nonexistent", "accepted")
        assert exc.value.status_code == 404

    @patch("httpx.Client.request")
    def test_resolve_invalid_action_422(self, mock_req, client):
        mock_req.return_value = _error_response(422, "invalid action")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.resolve_ontology_hitl("h1", "bogus")
        assert exc.value.status_code == 422

    @patch("httpx.Client.request")
    def test_resolve_server_error(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryServerError):
            client.resolve_ontology_hitl("h1", "accepted")
