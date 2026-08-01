"""PLAT-GRAPH-API-1i — `retrieved_context_ids` survives the client add() body build.

The bug: `MemoryItem.retrieved_context_ids` is a *first-class* field (not part of
`metadata`), and `SmartMemoryClient.add()` built its HTTP body from content /
memory_type / metadata / use_pipeline only. Any remote producer that set the typed
field — notably `service_common.conversations.ingest.record_turn`, which every Maya
assistant turn goes through — had it dropped in transit, losing the
CORE-DECISION-OUTCOME-1 D4 provenance that the `context_retention` evaluation
dimension is built on.

These tests assert the *mechanism* (what lands in the POST body), not just that
add() returns an id. Field contract:
`smart-memory-docs/docs/features/CORE-DECISION-OUTCOME-1/decision-outcome-contract.json`
(`memory_item_field_additions.fields.retrieved_context_ids`, incl. `transport_v1`).

All HTTP is mocked, mirroring tests/test_client_bughunt_fixes.py — no server needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient
from smartmemory_client.models.memory_item import MemoryItem

BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _ok_response(json_data: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = ""
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data if json_data is not None else {"id": "item-123"}
    return resp


def _sent_body(mock_req: MagicMock) -> Dict[str, Any]:
    return mock_req.call_args.kwargs["json"]


@dataclass
class _CoreLikeMemoryItem:
    """Stands in for smartmemory-core's MemoryItem.

    Deliberately NOT the SDK's MemoryItem: core's class is a different type, and
    add() duck-types it (`getattr(item, "content", None)`). record_turn passes
    exactly this shape, so the lift has to work on a foreign class.
    """

    content: str
    memory_type: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)
    retrieved_context_ids: List[str] = field(default_factory=list)


class TestExplicitParameter:
    @patch("httpx.Client.request")
    def test_ids_reach_the_body(self, mock_req, client):
        mock_req.return_value = _ok_response()

        client.add("a turn", retrieved_context_ids=["ctx-1", "ctx-2"])

        assert _sent_body(mock_req)["retrieved_context_ids"] == ["ctx-1", "ctx-2"]

    @patch("httpx.Client.request")
    def test_omitted_when_not_supplied(self, mock_req, client):
        """Absent means absent — the server owns the [] default, not the client."""
        mock_req.return_value = _ok_response()

        client.add("a turn")

        assert "retrieved_context_ids" not in _sent_body(mock_req)

    @patch("httpx.Client.request")
    def test_omitted_when_empty(self, mock_req, client):
        mock_req.return_value = _ok_response()

        client.add("a turn", retrieved_context_ids=[])

        assert "retrieved_context_ids" not in _sent_body(mock_req)

    @patch("httpx.Client.request")
    def test_tuple_is_normalized_to_list(self, mock_req, client):
        """JSON has no tuple — normalize rather than let the encoder decide."""
        mock_req.return_value = _ok_response()

        client.add("a turn", retrieved_context_ids=("ctx-1", "ctx-2"))

        assert _sent_body(mock_req)["retrieved_context_ids"] == ["ctx-1", "ctx-2"]


class TestLiftOffMemoryItem:
    """The regression that motivated the feature: record_turn's write path."""

    @patch("httpx.Client.request")
    def test_core_like_item_field_is_lifted(self, mock_req, client):
        mock_req.return_value = _ok_response()
        item = _CoreLikeMemoryItem(
            content="assistant turn text",
            metadata={"conversation_id": "conv-1", "role": "assistant"},
            retrieved_context_ids=["mem-a", "mem-b"],
        )

        client.add(item, use_pipeline=False)

        body = _sent_body(mock_req)
        assert body["retrieved_context_ids"] == ["mem-a", "mem-b"]
        # The rest of the turn contract must be unharmed by the lift.
        assert body["content"] == "assistant turn text"
        assert body["memory_type"] == "pending"
        assert body["use_pipeline"] is False

    @patch("httpx.Client.request")
    def test_sdk_memory_item_field_is_lifted(self, mock_req, client):
        mock_req.return_value = _ok_response()
        item = MemoryItem(
            item_id="",
            content="a turn",
            retrieved_context_ids=["mem-a"],
        )

        client.add(item)

        assert _sent_body(mock_req)["retrieved_context_ids"] == ["mem-a"]

    @patch("httpx.Client.request")
    def test_dict_item_field_is_lifted(self, mock_req, client):
        mock_req.return_value = _ok_response()

        client.add({"content": "a turn", "retrieved_context_ids": ["mem-a"]})

        assert _sent_body(mock_req)["retrieved_context_ids"] == ["mem-a"]

    @patch("httpx.Client.request")
    def test_explicit_parameter_overrides_item_field(self, mock_req, client):
        mock_req.return_value = _ok_response()
        item = _CoreLikeMemoryItem(
            content="a turn", retrieved_context_ids=["from-item"]
        )

        client.add(item, retrieved_context_ids=["from-caller"])

        assert _sent_body(mock_req)["retrieved_context_ids"] == ["from-caller"]

    @patch("httpx.Client.request")
    def test_item_without_the_field_omits_it(self, mock_req, client):
        """An item whose field is [] (the contract default) must not add noise."""
        mock_req.return_value = _ok_response()

        client.add(_CoreLikeMemoryItem(content="a turn"))

        assert "retrieved_context_ids" not in _sent_body(mock_req)


class TestReadBack:
    """GET /memory/{id} serializes the field since GRAPH-API-1i; the SDK model
    must carry it rather than silently discarding it in from_dict."""

    def test_from_dict_populates_the_field(self):
        item = MemoryItem.from_dict(
            {"item_id": "i-1", "content": "x", "retrieved_context_ids": ["ctx-1"]}
        )
        assert item.retrieved_context_ids == ["ctx-1"]

    def test_from_dict_defaults_to_empty_list_never_none(self):
        """Contract: `default_invariant: always [], never None`."""
        assert (
            MemoryItem.from_dict(
                {"item_id": "i-1", "content": "x"}
            ).retrieved_context_ids
            == []
        )
        assert (
            MemoryItem.from_dict(
                {"item_id": "i-1", "content": "x", "retrieved_context_ids": None}
            ).retrieved_context_ids
            == []
        )
