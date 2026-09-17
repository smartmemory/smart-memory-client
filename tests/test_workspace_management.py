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
