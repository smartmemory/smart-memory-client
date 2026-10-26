"""WS-ROUTING-4: ``set_session_workspace`` / ``clear_session_workspace`` (``PUT`` / ``DELETE /memory/routing/session``).

Real ``_request``, only ``httpx.Client.request`` is mocked. Field names are the contract's
(smart-memory-docs ``docs/features/WS-ROUTING-1/ws-routing-contract.json``).
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

RECORD = {
    "workspace_id": "ws_research",
    "client_key_digest": "0123456789ab",
    "context_key_digest": "-",
    "set_at": "2026-10-27T10:00:00+00:00",
    "set_via": "api",
    "expires_at": "2026-10-28T10:00:00+00:00",
    "client_key": "app:web",
    "context_key": None,
    "workspace_name": "Research",
}


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url="http://localhost:9001", api_key="test_token_abc123"
    )


def _ok(body) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = body
    return resp


def _error(status: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = f"error {status}"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status} Error", request=MagicMock(spec=httpx.Request), response=resp
    )
    return resp


# Columns: id, call, expected method, expected json body, expected query params.
CALL_ROWS = [
    (
        "set_without_context",
        lambda c: c.set_session_workspace("ws_research", "app:web"),
        "PUT",
        {"workspace_id": "ws_research", "client_key": "app:web"},
        None,
    ),
    (
        "set_with_context",
        lambda c: c.set_session_workspace(
            "ws_research", "app:web", context_key="repo:aaaaaaaaaaaa"
        ),
        "PUT",
        {
            "workspace_id": "ws_research",
            "client_key": "app:web",
            "context_key": "repo:aaaaaaaaaaaa",
        },
        None,
    ),
    (
        "clear_without_context",
        lambda c: c.clear_session_workspace("app:web"),
        "DELETE",
        None,
        {"client_key": "app:web"},
    ),
    (
        "clear_with_context",
        lambda c: c.clear_session_workspace(
            "app:web", context_key="repo:aaaaaaaaaaaa"
        ),
        "DELETE",
        None,
        {"client_key": "app:web", "context_key": "repo:aaaaaaaaaaaa"},
    ),
]


@pytest.mark.parametrize(
    ("row_id", "call", "method", "body", "params"),
    CALL_ROWS,
    ids=[r[0] for r in CALL_ROWS],
)
@patch("httpx.Client.request")
def test_session_workspace_calls_the_route(
    mock_request, client, row_id, call, method, body, params
):
    mock_request.return_value = _ok(RECORD)

    assert call(client) == RECORD
    sent_method, url = mock_request.call_args.args[:2]
    assert sent_method == method
    assert str(url) == "http://localhost:9001/memory/routing/session"
    assert mock_request.call_args.kwargs["json"] == body
    assert mock_request.call_args.kwargs["params"] == params


# Columns: status, exception. 403 not a member (or no such workspace), 409 workspace-bound key, 422 bad key grammar,
# 404 an older service without the route.
ERROR_ROWS = [
    (400, SmartMemoryValidationError),
    (401, SmartMemoryPermissionError),
    (403, SmartMemoryPermissionError),
    (404, SmartMemoryNotFoundError),
    (409, SmartMemoryValidationError),
    (422, SmartMemoryValidationError),
    (500, SmartMemoryServerError),
]
ERROR_CASES = [
    (name, status, exc) for name in ("set", "clear") for status, exc in ERROR_ROWS
]


@pytest.mark.parametrize(
    ("name", "status", "exception"),
    ERROR_CASES,
    ids=[f"{n}-{s}" for n, s, _ in ERROR_CASES],
)
@patch("httpx.Client.request")
def test_session_workspace_raises_typed_errors(
    mock_request, client, name, status, exception
):
    mock_request.return_value = _error(status)
    with pytest.raises(exception) as exc:
        if name == "set":
            client.set_session_workspace("ws_research", "app:web")
        else:
            client.clear_session_workspace("app:web")
    assert exc.value.status_code == status
    assert isinstance(exc.value, SmartMemoryClientError)
