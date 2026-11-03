"""SVC-WORKSPACE-ACCESS-1: ``get_workspace_access`` reads ``GET /memory/workspaces/{id}/access``.

Real ``_request``, only ``httpx.Client.request`` is mocked. Body fields are the contract's
(smart-memory-docs ``docs/features/SVC-WORKSPACE-ACCESS-1/workspace-access-contract.json``).
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

ACCESS_BODY = {
    "workspace_id": "ws_research",
    "teams": [
        {
            "team_id": "team_ops",
            "name": "Ops",
            "permission": "admin",
            "team_exists": True,
        },
        {
            "team_id": "team_gone",
            "name": None,
            "permission": "view",
            "team_exists": False,
        },
    ],
    "users": [{"user_id": "user_1", "permission": "admin"}],
}

ERROR_ROWS = [
    (400, SmartMemoryValidationError),
    (401, SmartMemoryPermissionError),
    (403, SmartMemoryPermissionError),
    (404, SmartMemoryNotFoundError),
    (422, SmartMemoryValidationError),
    (500, SmartMemoryServerError),
]


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url="http://localhost:9001", api_key="test_token_abc123"
    )


def _error(status: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = f"error {status}"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status} Error", request=MagicMock(spec=httpx.Request), response=resp
    )
    return resp


@patch("httpx.Client.request")
def test_get_workspace_access_returns_the_service_body(mock_request, client):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = ACCESS_BODY
    mock_request.return_value = resp

    assert client.get_workspace_access("ws_research") == ACCESS_BODY
    method, url = mock_request.call_args.args[:2]
    assert method == "GET"
    assert str(url).endswith("/memory/workspaces/ws_research/access")


@pytest.mark.parametrize(
    ("status", "exception"), ERROR_ROWS, ids=[str(s) for s, _ in ERROR_ROWS]
)
@patch("httpx.Client.request")
def test_get_workspace_access_raises_typed_errors(
    mock_request, client, status, exception
):
    mock_request.return_value = _error(status)
    with pytest.raises(exception) as exc:
        client.get_workspace_access("ws_research")
    assert exc.value.status_code == status
    assert isinstance(exc.value, SmartMemoryClientError)
