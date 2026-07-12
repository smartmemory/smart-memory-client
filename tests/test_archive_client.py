"""Tests for archive-first conversation client methods."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError


BASE_URL = "http://localhost:9001"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key="test_token_abc")


def _response(status_code: int, json_data: dict | None = None) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = "archive error"
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code} Error",
            request=MagicMock(spec=httpx.Request),
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    return response


@patch("httpx.Client.request")
def test_archive_put_sends_route_contract_and_returns_index_keys(mock_request, client):
    expected = {
        "archive_uri": "archive://conversation/turn-1",
        "content_hash": "sha256:abc",
    }
    mock_request.return_value = _response(200, expected)

    result = client.archive_put(
        "conversation-1",
        {"role": "user", "text": "Remember this."},
        {"content_type": "application/json"},
    )

    assert result == expected
    assert mock_request.call_args.args == ("POST", f"{BASE_URL}/memory/archive/store")
    assert mock_request.call_args.kwargs["json"] == {
        "conversation_id": "conversation-1",
        "payload": {"role": "user", "text": "Remember this."},
        "metadata": {"content_type": "application/json"},
    }


@patch("httpx.Client.request")
def test_archive_put_defaults_metadata_to_empty_object(mock_request, client):
    mock_request.return_value = _response(
        200,
        {"archive_uri": "archive://conversation/turn-1", "content_hash": "sha256:abc"},
    )

    client.archive_put("conversation-1", {"text": "Remember this."})

    assert mock_request.call_args.kwargs["json"]["metadata"] == {}


@patch("httpx.Client.request")
def test_archive_get_returns_route_payload_and_encodes_uri(mock_request, client):
    expected = {"payload": {"role": "user", "text": "Remember this."}}
    mock_request.return_value = _response(200, expected)

    result = client.archive_get("archive://conversation/turn 1")

    assert result == expected
    assert mock_request.call_args.args == (
        "GET",
        f"{BASE_URL}/memory/archive/archive%3A//conversation/turn%201",
    )


@patch("httpx.Client.request")
def test_archive_get_preserves_typed_not_found_error(mock_request, client):
    mock_request.return_value = _response(404)

    with pytest.raises(SmartMemoryClientError, match="Request failed"):
        client.archive_get("archive://conversation/missing")
