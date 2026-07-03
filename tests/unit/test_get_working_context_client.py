"""CORE-MEMORY-DYNAMICS-1 M1a / Task 6.2 — Python SDK get_working_context().

Tests request/response shape matches contract at
``smart-memory-docs/docs/features/CORE-MEMORY-DYNAMICS-1/context-api-contract.json``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError


@pytest.fixture
def client():
    return SmartMemoryClient(
        base_url="http://test.local:9001",
        api_key="test-token",
        team_id="test-team",
    )


_CONTRACT_RESPONSE = {
    "decision_id": "11111111-1111-1111-1111-111111111111",
    "items": [
        {
            "item_id": "i1",
            "content": "hello",
            "memory_type": "semantic",
            "metadata": {},
            "score_breakdown": {
                "activation": 0.5,
                "relevance": 0.9,
                "recency": 1.0,
                "centrality": 1.0,
                "anchor_forced": False,
                "session_pin_boost": 0.0,
                "freshness_boost": 0.0,
            },
        }
    ],
    "drift_warnings": [],
    "strategy_used": "fast:recency",
    "tokens_used": 3,
    "tokens_budget": None,
    "deprecation": None,
}


@patch("httpx.Client.request")
def test_happy_path_posts_to_memory_context(mock_req, client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CONTRACT_RESPONSE
    resp.raise_for_status.return_value = None
    mock_req.return_value = resp

    result = client.get_working_context(session_id="s1", query="hello")

    # Call shape
    args, kwargs = mock_req.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/memory/context")
    assert kwargs["json"]["session_id"] == "s1"
    assert kwargs["json"]["query"] == "hello"
    # Response passthrough
    assert result == _CONTRACT_RESPONSE


@patch("httpx.Client.request")
def test_optional_params_only_sent_when_set(mock_req, client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CONTRACT_RESPONSE
    resp.raise_for_status.return_value = None
    mock_req.return_value = resp

    client.get_working_context(
        session_id="s1", query="hello", k=10, max_tokens=500, strategy="fast:recency"
    )
    body = mock_req.call_args.kwargs["json"]
    assert body["k"] == 10
    assert body["max_tokens"] == 500
    assert body["strategy"] == "fast:recency"


@patch("httpx.Client.request")
def test_default_k_is_20(mock_req, client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CONTRACT_RESPONSE
    resp.raise_for_status.return_value = None
    mock_req.return_value = resp

    client.get_working_context(session_id="s1", query="hello")
    body = mock_req.call_args.kwargs["json"]
    assert body["k"] == 20


@patch("httpx.Client.request")
def test_sends_auth_and_workspace_headers(mock_req, client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CONTRACT_RESPONSE
    resp.raise_for_status.return_value = None
    mock_req.return_value = resp

    client.get_working_context(session_id="s1", query="hello")
    headers = mock_req.call_args.kwargs["headers"]
    assert headers.get("X-Workspace-Id") == "test-team"
    assert headers.get("Authorization") == "Bearer test-token"


@patch("httpx.Client.request")
def test_budget_too_small_raises(mock_req, client):
    """400 response with body {code: budget_too_small, ...} → SmartMemoryClientError."""
    resp = MagicMock()
    resp.status_code = 400
    resp.text = '{"detail":{"code":"budget_too_small","message":"..."}}'
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400", request=MagicMock(), response=resp
    )
    mock_req.return_value = resp

    with pytest.raises(SmartMemoryClientError, match="Request failed"):
        client.get_working_context(session_id="s1", query="hello", max_tokens=1)


@patch("httpx.Client.request")
def test_falsy_but_valid_max_tokens_zero_is_sent(mock_req, client):
    """Codex coverage: filter uses `is not None`, not truthiness — max_tokens=0
    (invalid by contract but syntactically not None) must be sent so server validates."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CONTRACT_RESPONSE
    resp.raise_for_status.return_value = None
    mock_req.return_value = resp

    client.get_working_context(session_id="s1", query="q", max_tokens=0)
    body = mock_req.call_args.kwargs["json"]
    assert "max_tokens" in body
    assert body["max_tokens"] == 0


@patch("httpx.Client.request")
def test_empty_strategy_string_is_sent(mock_req, client):
    """Codex coverage: strategy='' (empty string) is syntactically not None and
    must reach the server for validation — prevents truthiness-filter regressions."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CONTRACT_RESPONSE
    resp.raise_for_status.return_value = None
    mock_req.return_value = resp

    client.get_working_context(session_id="s1", query="q", strategy="")
    body = mock_req.call_args.kwargs["json"]
    assert body.get("strategy") == ""


@patch("httpx.Client.request")
def test_server_error_raises(mock_req, client):
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "Internal server error"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=resp
    )
    mock_req.return_value = resp

    with pytest.raises(SmartMemoryClientError):
        client.get_working_context(session_id="s1", query="hello")
