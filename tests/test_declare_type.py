"""CORE-MEMTYPE-DECLARE-1 T8 — declare_type / declare_relation SDK methods.

Wire-shape tests against the pinned contract
(`memory-type-contract.json`): exact field names, the declare endpoints, and
the required error statuses (400/409 validation, 500 server) per
`.claude/rules/error-coverage.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryServerError,
    SmartMemoryValidationError,
)
from smartmemory_client.client import SmartMemoryClient

CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "smart-memory-docs"
    / "docs"
    / "features"
    / "CORE-MEMTYPE-DECLARE-1"
    / "memory-type-contract.json"
)

SCHEMA = {
    "title": {"type": "string", "indexed": True},
    "attendees": {"type": "list", "of": "string"},
}


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


def _mock_response(json_payload, status: int = 201):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status: int, text: str = "error"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = {}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=resp
    )
    return resp


class TestDeclareType:
    @patch("httpx.Client.request")
    def test_declare_record_type_wire_shape(self, mock_req, client):
        mock_req.return_value = _mock_response(
            {"name": "fluid_event", "kind": "record"}
        )
        result = client.declare_type(
            "fluid_event",
            kind="record",
            properties_schema=SCHEMA,
            required_properties=["title"],
            storage_strategy="append",
            storage_searchable=False,
        )
        assert result["kind"] == "record"
        call = mock_req.call_args
        assert call[0][0] == "POST"
        assert call[0][1] == "http://localhost:9001/memory/ontology/types"
        body = call[1]["json"]
        # Exact contract field names (ontology_type_extensions + field_spec).
        assert body["name"] == "fluid_event"
        assert body["kind"] == "record"
        assert body["storage_strategy"] == "append"
        assert body["storage_searchable"] is False
        assert body["properties_schema"] == SCHEMA
        assert body["required_properties"] == ["title"]
        assert body["tier"] == "confirmed"

    @patch("httpx.Client.request")
    def test_entity_kind_defaults_omit_facet(self, mock_req, client):
        mock_req.return_value = _mock_response({"name": "Instrument", "kind": "entity"})
        client.declare_type("Instrument")
        body = mock_req.call_args[1]["json"]
        assert body == {"name": "Instrument", "kind": "entity", "tier": "confirmed"}

    @patch("httpx.Client.request")
    def test_validation_error_400(self, mock_req, client):
        mock_req.return_value = _error_response(400, "invalid properties_schema")
        with pytest.raises(SmartMemoryValidationError):
            client.declare_type(
                "fluid_event", kind="record", properties_schema={"f": {"type": "float"}}
            )

    @patch("httpx.Client.request")
    def test_shadowing_conflict_409(self, mock_req, client):
        mock_req.return_value = _error_response(409, "shadows the built-in memory type")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.declare_type("decision", kind="record")
        assert exc.value.status_code == 409

    @patch("httpx.Client.request")
    def test_server_error_500(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryServerError):
            client.declare_type("fluid_event", kind="record")


class TestDeclareRelation:
    @patch("httpx.Client.request")
    def test_declare_relation_wire_shape(self, mock_req, client):
        mock_req.return_value = _mock_response({"name": "informs"})
        client.declare_relation(
            "informs",
            domain=["fluid_idea"],
            range=["fluid_decision"],
            cardinality="N:N",
        )
        call = mock_req.call_args
        assert call[0][0] == "POST"
        assert call[0][1] == "http://localhost:9001/memory/ontology/relations"
        body = call[1]["json"]
        assert body["name"] == "informs"
        assert body["domain"] == ["fluid_idea"]
        assert body["range"] == ["fluid_decision"]
        assert body["cardinality"] == "N:N"
        assert body["tier"] == "confirmed"

    @patch("httpx.Client.request")
    def test_invalid_tier_400(self, mock_req, client):
        mock_req.return_value = _error_response(400, "invalid tier")
        with pytest.raises(SmartMemoryValidationError):
            client.declare_relation("informs", tier="canonical")

    @patch("httpx.Client.request")
    def test_server_error_500(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryServerError):
            client.declare_relation("informs")


class TestListKindFilter:
    @patch("httpx.Client.request")
    def test_kind_param_threads(self, mock_req, client):
        mock_req.return_value = _mock_response(
            {"items": [], "next_cursor": None}, status=200
        )
        client.list_ontology_types(kind="record")
        params = mock_req.call_args[1]["params"]
        assert params["kind"] == "record"


@pytest.mark.skipif(
    not CONTRACT.exists(), reason="sibling smart-memory-docs checkout not present"
)
class TestContractPin:
    def test_sdk_fields_match_contract(self):
        contract = json.loads(CONTRACT.read_text())
        ext = contract["ontology_type_extensions"]
        assert ext["kind"]["enum"] == ["entity", "record"]
        assert ext["kind"]["default"] == "entity"
        assert ext["storage_strategy"]["enum"] == ["full", "indexed", "append"]
        # field_spec keys the SDK passes through verbatim in properties_schema.
        spec_keys = {k for k in contract["field_spec"] if not k.startswith("_")}
        assert spec_keys == {"type", "of", "default", "indexed", "append_only"}
        assert contract["field_spec"]["type"]["enum"] == [
            "string",
            "integer",
            "number",
            "boolean",
            "datetime",
            "object",
            "list",
        ]
