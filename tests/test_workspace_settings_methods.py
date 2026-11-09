"""Tests for the workspace and tenant settings SDK methods (WS-MGMT-16-FU, contract ``modules.settings``)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)
from smartmemory_client.client import SmartMemoryClient

BASE = "http://localhost:9001"
PATCH_BODY = {"review": {"supersession": "propose"}}


@pytest.fixture
def client():
    return SmartMemoryClient(base_url=BASE, api_key="test-token", workspace_id="ws1")


def _ok(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _error(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "error"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status_code), request=MagicMock(), response=resp
    )
    return resp


SETTINGS = {
    "scope": "workspace",
    "scope_id": "ws1",
    "version": 4,
    "stated": PATCH_BODY,
    "effective": PATCH_BODY,
    "source": {"review": {"supersession": "workspace"}},
    "read_only": {},
}

# (name, call, method, path, expected json body)
CALLS = [
    (
        "get_ws",
        lambda c, **k: c.get_workspace_settings("ws9"),
        "GET",
        "/memory/workspaces/ws9/settings",
        None,
    ),
    (
        "get_ws_default",
        lambda c, **k: c.get_workspace_settings(),
        "GET",
        "/memory/workspaces/ws1/settings",
        None,
    ),
    (
        "patch_ws",
        lambda c, **k: c.update_workspace_settings(PATCH_BODY, "ws9", **k),
        "PATCH",
        "/memory/workspaces/ws9/settings",
        {"stated": PATCH_BODY},
    ),
    (
        "get_tenant",
        lambda c, **k: c.get_tenant_settings(),
        "GET",
        "/memory/tenant/settings",
        None,
    ),
    (
        "patch_tenant",
        lambda c, **k: c.update_tenant_settings(PATCH_BODY, **k),
        "PATCH",
        "/memory/tenant/settings",
        {"stated": PATCH_BODY},
    ),
]


class TestSettingsRoutes:
    @pytest.mark.parametrize(
        "name,call,method,path,body", CALLS, ids=[c[0] for c in CALLS]
    )
    @patch("httpx.Client.request")
    def test_hits_route_and_returns_record(
        self, mock_req, name, call, method, path, body, client
    ):
        mock_req.return_value = _ok(SETTINGS)
        assert call(client) == SETTINGS
        args, kwargs = mock_req.call_args
        assert args == (method, f"{BASE}{path}")
        assert kwargs["json"] == body
        assert "If-Match" not in kwargs["headers"]

    @pytest.mark.parametrize(
        "name,call,method,path,body", CALLS[2::2], ids=["patch_ws", "patch_tenant"]
    )
    @patch("httpx.Client.request")
    def test_patch_sends_if_match(
        self, mock_req, name, call, method, path, body, client
    ):
        mock_req.return_value = _ok(SETTINGS)
        call(client, if_match=4)
        assert mock_req.call_args.kwargs["headers"]["If-Match"] == "4"

    @patch("httpx.Client.request")
    def test_null_restores_inheritance(self, mock_req, client):
        mock_req.return_value = _ok(SETTINGS)
        client.update_workspace_settings({"review": {"supersession": None}})
        assert mock_req.call_args.kwargs["json"] == {
            "stated": {"review": {"supersession": None}}
        }


class TestSettingsErrors:
    @pytest.mark.parametrize(
        "status,exc",
        [
            (403, SmartMemoryPermissionError),
            (409, SmartMemoryValidationError),
            (503, SmartMemoryServerError),
        ],
    )
    @patch("httpx.Client.request")
    def test_status_maps_to_typed_error(self, mock_req, status, exc, client):
        mock_req.return_value = _error(status)
        for call in (
            lambda: client.get_workspace_settings(),
            lambda: client.update_workspace_settings(PATCH_BODY, if_match=1),
            lambda: client.get_tenant_settings(),
            lambda: client.update_tenant_settings(PATCH_BODY, if_match=1),
        ):
            with pytest.raises(exc) as info:
                call()
            assert info.value.status_code == status


class TestSupersessionHelpersOnSettings:
    @patch("httpx.Client.request")
    def test_helpers_keep_their_shape(self, mock_req, client):
        mock_req.return_value = _ok(SETTINGS)
        expected = {
            "workspace_id": "ws1",
            "policy": "propose",
            "source": "workspace",
            "stated": "propose",
            "version": 4,
        }
        assert client.get_supersession_policy() == expected
        assert client.set_supersession_policy("propose", if_match=4) == expected
        kwargs = mock_req.call_args.kwargs
        assert kwargs["json"] == {"stated": PATCH_BODY}
        assert kwargs["headers"]["If-Match"] == "4"
