"""Tests for ontology read/audit/migration client SDK methods (ONTO-CRUD-1)."""

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


class TestListOntologyTypes:
    @patch("httpx.Client.request")
    def test_list_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {"items": [{"name": "Person"}], "next_cursor": None}
        )
        result = client.list_ontology_types()
        assert result["items"][0]["name"] == "Person"
        call = mock_req.call_args
        assert call[0][0] == "GET"
        assert call[0][1] == "http://localhost:9001/memory/ontology/types"
        assert call[1]["params"] == {"limit": 100}

    @patch("httpx.Client.request")
    def test_list_with_filters(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": [], "next_cursor": "abc"})
        client.list_ontology_types(
            tier="confirmed",
            layer="public",
            pack_id="pack-1",
            has_iri=True,
            limit=10,
            cursor="c1",
        )
        params = mock_req.call_args[1]["params"]
        assert params == {
            "limit": 10,
            "tier": "confirmed",
            "layer": "public",
            "pack_id": "pack-1",
            "has_iri": True,
            "cursor": "c1",
        }

    @patch("httpx.Client.request")
    def test_list_bad_cursor_400(self, mock_req, client):
        mock_req.return_value = _error_response(400, "invalid cursor")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.list_ontology_types(cursor="bogus")
        assert exc.value.status_code == 400


class TestListOntologyRelations:
    @patch("httpx.Client.request")
    def test_list_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {"items": [{"name": "WORKS_AT"}], "next_cursor": None}
        )
        result = client.list_ontology_relations()
        assert result["items"][0]["name"] == "WORKS_AT"
        call = mock_req.call_args
        assert call[0][1] == "http://localhost:9001/memory/ontology/relations"
        assert call[1]["params"] == {"limit": 100}

    @patch("httpx.Client.request")
    def test_list_with_filters(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": [], "next_cursor": None})
        client.list_ontology_relations(tier="proposed", has_iri=False, limit=25)
        params = mock_req.call_args[1]["params"]
        assert params == {"limit": 25, "tier": "proposed", "has_iri": False}


class TestGetOntologyType:
    @patch("httpx.Client.request")
    def test_get_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"name": "Person", "tier": "confirmed"})
        result = client.get_ontology_type("Person")
        assert result["name"] == "Person"
        call = mock_req.call_args
        assert call[0][1] == "http://localhost:9001/memory/ontology/types/Person"

    @patch("httpx.Client.request")
    def test_get_not_found(self, mock_req, client):
        mock_req.return_value = _error_response(404, "not found")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.get_ontology_type("nonexistent")
        assert exc.value.status_code == 404


class TestGetOntologyRelation:
    @patch("httpx.Client.request")
    def test_get_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"name": "WORKS_AT"})
        result = client.get_ontology_relation("WORKS_AT")
        assert result["name"] == "WORKS_AT"
        call = mock_req.call_args
        assert call[0][1] == "http://localhost:9001/memory/ontology/relations/WORKS_AT"


class TestOntologyAuditFeeds:
    @patch("httpx.Client.request")
    def test_list_audit_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": [{"action": "migrate"}]})
        result = client.list_ontology_audit()
        assert result["items"][0]["action"] == "migrate"
        params = mock_req.call_args[1]["params"]
        assert params == {"limit": 200}

    @patch("httpx.Client.request")
    def test_list_audit_with_filters(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": []})
        client.list_ontology_audit(
            actor="user-1",
            action="retire",
            since="2026-01-01T00:00:00Z",
            until="2026-02-01T00:00:00Z",
            limit=50,
        )
        params = mock_req.call_args[1]["params"]
        assert params == {
            "limit": 50,
            "actor": "user-1",
            "action": "retire",
            "since": "2026-01-01T00:00:00Z",
            "until": "2026-02-01T00:00:00Z",
        }

    @patch("httpx.Client.request")
    def test_get_type_audit(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": [{"action": "create"}]})
        result = client.get_ontology_type_audit("Person")
        assert result["items"][0]["action"] == "create"
        call = mock_req.call_args
        assert call[0][1] == "http://localhost:9001/memory/ontology/types/Person/audit"

    @patch("httpx.Client.request")
    def test_get_relation_audit(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": []})
        client.get_ontology_relation_audit("WORKS_AT")
        call = mock_req.call_args
        assert (
            call[0][1]
            == "http://localhost:9001/memory/ontology/relations/WORKS_AT/audit"
        )

    @patch("httpx.Client.request")
    def test_get_pack_audit_no_version(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": []})
        client.get_ontology_pack_audit("pack-1")
        call = mock_req.call_args
        assert call[0][1] == "http://localhost:9001/memory/ontology/packs/pack-1/audit"
        assert call[1]["params"] == {}

    @patch("httpx.Client.request")
    def test_get_pack_audit_with_version(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": []})
        client.get_ontology_pack_audit("pack-1", pack_version="v2")
        call = mock_req.call_args
        assert call[1]["params"] == {"pack_version": "v2"}

    @patch("httpx.Client.request")
    def test_list_audit_server_error(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryServerError):
            client.list_ontology_audit()


class TestMigrateOntologyTypeInstances:
    @patch("httpx.Client.request")
    def test_migrate_basic(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "from_name": "OldType",
                "into_name": "NewType",
                "instances_migrated": 12,
                "batches": 1,
                "notes": [],
            }
        )
        result = client.migrate_ontology_type_instances(
            "OldType", "NewType", reason="consolidation"
        )
        assert result["instances_migrated"] == 12
        call = mock_req.call_args
        assert call[0][0] == "POST"
        assert (
            call[0][1]
            == "http://localhost:9001/memory/ontology/types/OldType/migrate-to/NewType"
        )
        assert call[1]["json"] == {"reason": "consolidation", "batch_size": 500}

    @patch("httpx.Client.request")
    def test_migrate_custom_batch_size(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "from_name": "A",
                "into_name": "B",
                "instances_migrated": 0,
                "batches": 0,
                "notes": [],
            }
        )
        client.migrate_ontology_type_instances("A", "B", reason="test", batch_size=100)
        assert mock_req.call_args[1]["json"] == {"reason": "test", "batch_size": 100}

    @patch("httpx.Client.request")
    def test_migrate_skip_violation_mode_and_report(
        self, mock_req, client, mock_response
    ):
        mock_req.return_value = mock_response(
            {
                "from_name": "RecordA",
                "into_name": "RecordB",
                "instances_migrated": 1,
                "batches": 1,
                "notes": [],
                "moved_item_ids": ["item-1"],
                "skipped_items": {"item-2": ["priority: expected integer"]},
                "vector_metadata_updated": 1,
                "vector_metadata_missing": 0,
                "vector_metadata_failed": 0,
                "searchable_mismatch_count": 1,
            }
        )

        result = client.migrate_ontology_type_instances(
            "RecordA", "RecordB", reason="schema repair", on_violation="skip"
        )

        assert mock_req.call_args[1]["json"] == {
            "reason": "schema repair",
            "batch_size": 500,
            "on_violation": "skip",
        }
        assert result["moved_item_ids"] == ["item-1"]
        assert result["skipped_items"] == {"item-2": ["priority: expected integer"]}
        assert result["vector_metadata_updated"] == 1
        assert result["vector_metadata_missing"] == 0
        assert result["vector_metadata_failed"] == 0
        assert result["searchable_mismatch_count"] == 1

    @patch("httpx.Client.request")
    def test_migrate_self_migration_400(self, mock_req, client):
        mock_req.return_value = _error_response(400, "cannot migrate into itself")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.migrate_ontology_type_instances("A", "A", reason="oops")
        assert exc.value.status_code == 400

    @patch("httpx.Client.request")
    def test_migrate_not_found_404(self, mock_req, client):
        mock_req.return_value = _error_response(404, "not found")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.migrate_ontology_type_instances("Missing", "B", reason="test")
        assert exc.value.status_code == 404
