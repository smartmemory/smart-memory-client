"""Tests for graph read and bulk-write SmartMemoryClient methods."""

from unittest.mock import MagicMock, patch

import pytest

from smartmemory_client.client import SmartMemoryClient


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


@pytest.fixture
def mock_response():
    def _make(json_data: dict) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = json_data
        response.raise_for_status.return_value = None
        return response

    return _make


class TestGraphAPIMethods:
    @patch("httpx.Client.request")
    def test_get_edges_bulk(self, mock_request, client, mock_response):
        mock_request.return_value = mock_response({"edges": [], "count": 0})

        result = client.get_edges_bulk(["node-1", "node-2"], include_properties=True)

        assert result == {"edges": [], "count": 0}
        assert mock_request.call_args.args[0] == "POST"
        assert (
            mock_request.call_args.args[1] == "http://localhost:9001/memory/graph/edges"
        )
        assert mock_request.call_args.kwargs["params"] == {"include_properties": True}
        assert mock_request.call_args.kwargs["json"] == {
            "node_ids": ["node-1", "node-2"]
        }

    @patch("httpx.Client.request")
    def test_bulk_graph_upsert(self, mock_request, client, mock_response):
        mock_request.return_value = mock_response(
            {"nodes_upserted": 1, "edges_upserted": 1, "nodes_deleted": 2}
        )

        result = client.bulk_graph_upsert(
            nodes=[
                {"item_id": "node-1", "label": "Person", "properties": {"name": "Ada"}}
            ],
            edges=[
                {"source_id": "node-1", "target_id": "node-2", "edge_type": "KNOWS"}
            ],
            delete_prefix="import:",
        )

        assert result["nodes_deleted"] == 2
        assert mock_request.call_args.args[0] == "POST"
        assert (
            mock_request.call_args.args[1] == "http://localhost:9001/memory/graph/bulk"
        )
        assert mock_request.call_args.kwargs["json"] == {
            "nodes": [
                {"item_id": "node-1", "label": "Person", "properties": {"name": "Ada"}}
            ],
            "edges": [
                {"source_id": "node-1", "target_id": "node-2", "edge_type": "KNOWS"}
            ],
            "delete_prefix": "import:",
        }

    @patch("httpx.Client.request")
    def test_get_graph_path(self, mock_request, client, mock_response):
        mock_request.return_value = mock_response(
            {"path_found": True, "hops": 1, "path": [{"id": "node-1", "type": "node"}]}
        )

        result = client.get_graph_path("node-1", "node-2", max_hops=3)

        assert result["path_found"] is True
        assert mock_request.call_args.args[0] == "GET"
        assert (
            mock_request.call_args.args[1] == "http://localhost:9001/memory/graph/path"
        )
        assert mock_request.call_args.kwargs["params"] == {
            "start_id": "node-1",
            "end_id": "node-2",
            "max_hops": 3,
        }

    @patch("httpx.Client.request")
    def test_get_graph_full(self, mock_request, client, mock_response):
        mock_request.return_value = mock_response(
            {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}
        )

        result = client.get_graph_full(limit=25)

        assert result["node_count"] == 0
        assert mock_request.call_args.args[0] == "GET"
        assert (
            mock_request.call_args.args[1] == "http://localhost:9001/memory/graph/full"
        )
        assert mock_request.call_args.kwargs["params"] == {"limit": 25}
