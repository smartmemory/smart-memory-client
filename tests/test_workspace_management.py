"""Contract tests for Workspace management SDK methods."""

from unittest.mock import patch

import pytest

from smartmemory_client.client import SmartMemoryClient


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(api_key="test-key", base_url="http://test-url")


@pytest.fixture
def mock_request(client: SmartMemoryClient):
    with patch.object(client, "_request") as request:
        yield request


def test_list_workspaces_uses_management_endpoint(client, mock_request):
    expected = {"workspaces": []}
    mock_request.return_value = expected

    assert client.list_workspaces() == expected
    mock_request.assert_called_once_with("GET", "/memory/workspaces")


def test_create_workspace_sends_contract_body(client, mock_request):
    expected = {
        "workspace_id": "ws_research",
        "tenant_id": "tenant_abc",
        "name": "Research",
        "description": None,
        "is_personal": False,
        "effective_permission": "admin",
        "sharing_count": 1,
        "can_manage_shares": True,
    }
    mock_request.return_value = expected

    result = client.create_workspace("Research", "team_abc")

    assert result == expected
    mock_request.assert_called_once_with(
        "POST",
        "/memory/workspaces",
        json_body={
            "name": "Research",
            "description": None,
            "team_id": "team_abc",
        },
    )


def test_create_workspace_sends_description(client, mock_request):
    client.create_workspace("Research", "team_abc", description="Shared notes")

    mock_request.assert_called_once_with(
        "POST",
        "/memory/workspaces",
        json_body={
            "name": "Research",
            "description": "Shared notes",
            "team_id": "team_abc",
        },
    )


def test_share_workspace_sends_contract_body(client, mock_request):
    expected = {
        "workspace_id": "ws_research",
        "team_id": "team_reviewers",
        "permission": "view",
    }
    mock_request.return_value = expected

    result = client.share_workspace("ws_research", "team_reviewers", "view")

    assert result == expected
    mock_request.assert_called_once_with(
        "POST",
        "/memory/workspaces/ws_research/share",
        json_body={"team_id": "team_reviewers", "permission": "view"},
    )


def test_revoke_workspace_share_uses_team_path(client, mock_request):
    mock_request.return_value = None

    assert client.revoke_workspace_share("ws_research", "team_reviewers") is None
    mock_request.assert_called_once_with(
        "DELETE", "/memory/workspaces/ws_research/share/team_reviewers"
    )


def test_list_team_workspaces_uses_team_endpoint(client, mock_request):
    expected = {"team_id": "team_reviewers", "workspaces": []}
    mock_request.return_value = expected

    assert client.list_team_workspaces("team_reviewers") == expected
    mock_request.assert_called_once_with(
        "GET", "/memory/teams/team_reviewers/workspaces"
    )


# ---- WS-MGMT-12: workspace lifecycle methods ------------------------------------------

import httpx  # noqa: E402

from smartmemory_client.client import (  # noqa: E402
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

HIDDEN = {
    "workspace_id": "ws_1",
    "state": "hidden",
    "restore_until": "2026-11-23T00:00:00Z",
}
DETAIL = {"workspace_id": "ws_1", "name": "N", "state": "active", "restore_until": None}

# (label, call, verb, path, params, json_body, response)
LIFECYCLE_ROWS = [
    (
        "get",
        lambda c: c.get_workspace("ws_1"),
        "GET",
        "/memory/workspaces/ws_1",
        None,
        None,
        DETAIL,
    ),
    (
        "update_name",
        lambda c: c.update_workspace("ws_1", name="N"),
        "PATCH",
        "/memory/workspaces/ws_1",
        None,
        {"name": "N"},
        DETAIL,
    ),
    (
        "update_desc",
        lambda c: c.update_workspace("ws_1", description="d"),
        "PATCH",
        "/memory/workspaces/ws_1",
        None,
        {"description": "d"},
        DETAIL,
    ),
    (
        "update_both",
        lambda c: c.update_workspace("ws_1", name="N", description="d"),
        "PATCH",
        "/memory/workspaces/ws_1",
        None,
        {"name": "N", "description": "d"},
        DETAIL,
    ),
    (
        "delete",
        lambda c: c.delete_workspace("ws_1"),
        "DELETE",
        "/memory/workspaces/ws_1",
        None,
        None,
        HIDDEN,
    ),
    (
        "restore",
        lambda c: c.restore_workspace("ws_1"),
        "POST",
        "/memory/workspaces/ws_1/restore",
        None,
        None,
        DETAIL,
    ),
    (
        "list_default",
        lambda c: c.list_workspaces(),
        "GET",
        "/memory/workspaces",
        None,
        None,
        {"workspaces": []},
    ),
    (
        "list_false",
        lambda c: c.list_workspaces(include_hidden=False),
        "GET",
        "/memory/workspaces",
        None,
        None,
        {"workspaces": []},
    ),
    (
        "list_hidden",
        lambda c: c.list_workspaces(include_hidden=True),
        "GET",
        "/memory/workspaces",
        {"include": "hidden"},
        None,
        {"workspaces": []},
    ),
]

ERROR_ROWS = [
    (403, SmartMemoryPermissionError),
    (404, SmartMemoryNotFoundError),
    (409, SmartMemoryValidationError),
    (503, SmartMemoryServerError),
]

ERROR_CALLS = [
    ("get", lambda c: c.get_workspace("ws_1")),
    ("update", lambda c: c.update_workspace("ws_1", name="N")),
    ("delete", lambda c: c.delete_workspace("ws_1")),
    ("restore", lambda c: c.restore_workspace("ws_1")),
]


def _http_response(status: int, body: dict | None = None) -> httpx.Response:
    request = httpx.Request("GET", "http://test-url/memory/workspaces/ws_1")
    return httpx.Response(status, json=body or {}, request=request)


@pytest.mark.parametrize("row", LIFECYCLE_ROWS, ids=[r[0] for r in LIFECYCLE_ROWS])
def test_lifecycle_request_shape_and_result(client, row):
    _, call, verb, path, params, body, response = row
    with patch.object(
        client._client, "request", return_value=_http_response(200, response)
    ) as req:
        assert call(client) == response
    req.assert_called_once()
    args, kwargs = req.call_args
    assert args == (verb, f"http://test-url{path}")
    assert kwargs["params"] == params
    assert kwargs["json"] == body


def test_delete_workspace_returns_202_body(client):
    with patch.object(
        client._client, "request", return_value=_http_response(202, HIDDEN)
    ) as req:
        assert client.delete_workspace("ws_1") == HIDDEN
    assert req.call_count == 1


def test_update_workspace_without_fields_raises_before_request(client):
    with patch.object(client._client, "request") as req:
        with pytest.raises(ValueError):
            client.update_workspace("ws_1")
    req.assert_not_called()


# One explicit row table (no stacked parametrize): method x status.
ERROR_TABLE = [
    (n, call, status, exc) for n, call in ERROR_CALLS for status, exc in ERROR_ROWS
]


@pytest.mark.parametrize(
    "name,call,status,exc", ERROR_TABLE, ids=[f"{r[0]}-{r[2]}" for r in ERROR_TABLE]
)
def test_lifecycle_errors_use_existing_mapping(client, name, call, status, exc):
    with patch.object(client._client, "request", return_value=_http_response(status)):
        with pytest.raises(exc) as info:
            call(client)
    assert info.value.status_code == status
