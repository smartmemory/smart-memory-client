"""BUG-MCP-ACTIVATE-STAGED-REASON-1: ``try_activate_decision`` carries the optional ``reason``.

Frozen notes ``smart-memory-ops/units/BUG-MCP-ACTIVATE-STAGED-REASON-1/notes-frozen.md`` rows P1-P2. Contract
``smart-memory-docs/docs/plans/contracts/decisions.json`` ``api.activate_response``. Same transport double as
``test_pending_decision_methods.py``.
"""

import typing
from unittest.mock import MagicMock, patch

import pytest

from smartmemory_client import models
from smartmemory_client.client import SmartMemoryClient
from smartmemory_client.models.decisions import DecisionActivation


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


def _response(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


@patch("httpx.Client.request")
def test_p1_a_staged_reply_is_returned_with_its_reason(mock_req, client):
    mock_req.return_value = _response(
        {"activated": False, "decision": None, "reason": "staged"}
    )
    assert client.try_activate_decision("dec_1") == {
        "activated": False,
        "decision": None,
        "reason": "staged",
    }


@patch("httpx.Client.request")
def test_p2_a_reply_without_a_reason_gets_no_key_added(mock_req, client):
    mock_req.return_value = _response({"activated": False, "decision": None})
    out = client.try_activate_decision("dec_1")
    assert out == {"activated": False, "decision": None}
    assert "reason" not in out


def test_p1_the_type_names_reason_as_optional_staged():
    hints = typing.get_type_hints(SmartMemoryClient.try_activate_decision)
    assert hints["return"] is DecisionActivation
    assert DecisionActivation.__required_keys__ == {"activated", "decision"}
    assert DecisionActivation.__optional_keys__ == {"reason"}
    reason = typing.get_type_hints(DecisionActivation)["reason"]
    assert typing.get_args(reason) == ("staged",)
    assert models.DecisionActivation is DecisionActivation
