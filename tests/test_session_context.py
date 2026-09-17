"""AUTH-IDENTITY-MODEL-1 SDK session-context compatibility tests."""

from unittest.mock import MagicMock

from smartmemory_client import SessionResponse, SmartMemoryClient


def test_workspace_id_is_primary_and_team_id_delegates() -> None:
    client = SmartMemoryClient(
        "http://test", api_key="test-key", workspace_id="workspace-primary"
    )

    assert client.workspace_id == "workspace-primary"
    assert client.team_id == client.workspace_id

    client.team_id = "workspace-through-legacy-alias"

    assert client.workspace_id == "workspace-through-legacy-alias"
    assert client.headers["X-Workspace-Id"] == "workspace-through-legacy-alias"


def test_workspace_environment_name_is_preferred(monkeypatch) -> None:
    monkeypatch.setenv("SMARTMEMORY_WORKSPACE_ID", "workspace-new-env")
    monkeypatch.setenv("SMARTMEMORY_TEAM_ID", "workspace-old-env")

    client = SmartMemoryClient("http://test", api_key="test-key")

    assert client.workspace_id == "workspace-new-env"
    assert client.team_id == "workspace-new-env"


def test_get_me_prefers_default_workspace_id_and_remains_indexable() -> None:
    client = SmartMemoryClient("http://test", api_key="test-key")
    client._request = MagicMock(
        return_value={
            "id": "user-1",
            "default_workspace_id": "workspace-new",
            "default_team_id": "workspace-old-alias",
            "active_workspace_id": "workspace-active",
            "tenant_id": "tenant-1",
            "tenant_role": "owner",
        }
    )

    session: SessionResponse = client.get_me()

    assert isinstance(session, dict)
    assert session["default_workspace_id"] == "workspace-new"
    assert session["default_team_id"] == "workspace-old-alias"
    assert session["active_workspace_id"] == "workspace-active"


def test_session_parsing_falls_back_to_default_team_id() -> None:
    client = SmartMemoryClient("http://test", api_key="test-key")
    client._request = MagicMock(
        return_value={
            "id": "user-1",
            "default_team_id": "workspace-legacy",
            "tenant_id": "tenant-1",
            "tenant_role": "member",
        }
    )

    session = client.get_me()

    assert session["default_workspace_id"] == "workspace-legacy"
    assert session["default_team_id"] == "workspace-legacy"


def test_refresh_token_returns_typed_dict_compatible_session() -> None:
    client = SmartMemoryClient("http://test", api_key="test-key")
    client._request = MagicMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "default_team_id": "workspace-legacy",
        }
    )

    session: SessionResponse = client.refresh_token("old-refresh")

    assert session["access_token"] == "new-access"
    assert session["default_workspace_id"] == "workspace-legacy"
    assert client._token == "new-access"
    assert client._refresh_token == "new-refresh"
