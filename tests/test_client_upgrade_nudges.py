"""UPGRADE-NUDGES-9: ``get_next_upgrade_nudge`` and ``record_upgrade_nudge_*``.

Real ``_request``, only ``httpx.Client.request`` is mocked. Routes, query and bodies are the
``endpoint`` section of smart-memory-docs
``docs/features/UPGRADE-NUDGES-1/upgrade-nudges-contract.json`` (service 11c04b30). No live server.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE = "http://localhost:9001"
NUDGE = {
    "nudge_key": "banner-sso",
    "kind": "banner",
    "surface": "web",
    "target_tier": "enterprise",
    "audience": "billing_manager",
    "anchor": "cap-sso",
    "copy": "Your organization has 5 members.",
    "actions": {"compare": "Compare plans", "dismiss": "Not now"},
}


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE, api_key="test_token_abc123")


def _ok(body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = body
    return resp


def _error(status: int, text: str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status}", request=MagicMock(), response=resp
    )
    return resp


# One explicit row per route and parameter shape. Record routes send no body.
REQUEST_ROWS = [
    (
        "next_default_surface",
        lambda c: c.get_next_upgrade_nudge(),
        "GET",
        "/upgrade-nudges/next",
        {"surface": "web"},
        {"nudge": NUDGE},
    ),
    (
        "next_explicit_surface",
        lambda c: c.get_next_upgrade_nudge(surface="web"),
        "GET",
        "/upgrade-nudges/next",
        {"surface": "web"},
        {"nudge": NUDGE},
    ),
    (
        "next_null_nudge_untouched",
        lambda c: c.get_next_upgrade_nudge(),
        "GET",
        "/upgrade-nudges/next",
        {"surface": "web"},
        {"nudge": None},
    ),
    (
        "shown",
        lambda c: c.record_upgrade_nudge_shown("banner-sso"),
        "POST",
        "/upgrade-nudges/banner-sso/shown",
        None,
        {"recorded": True},
    ),
    (
        "clicked",
        lambda c: c.record_upgrade_nudge_clicked("banner-sso"),
        "POST",
        "/upgrade-nudges/banner-sso/clicked",
        None,
        {"recorded": True},
    ),
    (
        "dismissed",
        lambda c: c.record_upgrade_nudge_dismissed("banner-sso"),
        "POST",
        "/upgrade-nudges/banner-sso/dismissed",
        None,
        {"recorded": True},
    ),
    (
        "shown_not_recorded_is_a_200",
        lambda c: c.record_upgrade_nudge_shown("banner-sso"),
        "POST",
        "/upgrade-nudges/banner-sso/shown",
        None,
        {"recorded": False},
    ),
    (
        "key_is_url_quoted",
        lambda c: c.record_upgrade_nudge_clicked("a/b c"),
        "POST",
        "/upgrade-nudges/a%2Fb%20c/clicked",
        None,
        {"recorded": True},
    ),
]


@pytest.mark.parametrize(
    "call,method,path,params,response",
    [row[1:] for row in REQUEST_ROWS],
    ids=[row[0] for row in REQUEST_ROWS],
)
@patch("httpx.Client.request")
def test_sends_the_contract_request_and_returns_the_body_untouched(
    mock_request, client, call, method, path, params, response
):
    mock_request.return_value = _ok(response)
    assert call(client) == response
    assert mock_request.call_args.args == (method, f"{BASE}{path}")
    kwargs = mock_request.call_args.kwargs
    assert kwargs["params"] == params
    assert kwargs["json"] is None
    assert kwargs["data"] is None


RECORD_CALLS = [
    ("shown", lambda c, k: c.record_upgrade_nudge_shown(k)),
    ("clicked", lambda c, k: c.record_upgrade_nudge_clicked(k)),
    ("dismissed", lambda c, k: c.record_upgrade_nudge_dismissed(k)),
]


@pytest.mark.parametrize(
    "call", [row[1] for row in RECORD_CALLS], ids=[row[0] for row in RECORD_CALLS]
)
@pytest.mark.parametrize("bad", [None, "", 7], ids=["none", "empty", "int"])
@patch("httpx.Client.request")
def test_record_raises_before_any_request_on_a_missing_or_empty_key(
    mock_request, client, call, bad
):
    with pytest.raises(ValueError):
        call(client, bad)
    mock_request.assert_not_called()


# One row per status the contract lists (404 unknown_nudge_key, 422 validation_error) plus 500.
ERROR_ROWS = [
    (
        "next_422",
        lambda c: c.get_next_upgrade_nudge(surface="studio"),
        422,
        '{"detail": {"code": "validation_error"}}',
        SmartMemoryValidationError,
    ),
    (
        "shown_404",
        lambda c: c.record_upgrade_nudge_shown("nope"),
        404,
        '{"detail": {"code": "unknown_nudge_key"}}',
        SmartMemoryNotFoundError,
    ),
    (
        "clicked_404",
        lambda c: c.record_upgrade_nudge_clicked("nope"),
        404,
        '{"detail": {"code": "unknown_nudge_key"}}',
        SmartMemoryNotFoundError,
    ),
    (
        "dismissed_404",
        lambda c: c.record_upgrade_nudge_dismissed("nope"),
        404,
        '{"detail": {"code": "unknown_nudge_key"}}',
        SmartMemoryNotFoundError,
    ),
    (
        "next_500",
        lambda c: c.get_next_upgrade_nudge(),
        500,
        "boom",
        SmartMemoryServerError,
    ),
    (
        "shown_500",
        lambda c: c.record_upgrade_nudge_shown("k"),
        500,
        "boom",
        SmartMemoryServerError,
    ),
]


@pytest.mark.parametrize(
    "call,status,text,exc_cls",
    [row[1:] for row in ERROR_ROWS],
    ids=[row[0] for row in ERROR_ROWS],
)
@patch("httpx.Client.request")
def test_contract_statuses_raise_the_typed_error(
    mock_request, client, call, status, text, exc_cls
):
    mock_request.return_value = _error(status, text)
    with pytest.raises(exc_cls) as info:
        call(client)
    assert type(info.value) is exc_cls
    assert info.value.status_code == status
    assert text in str(info.value.detail)


@patch("httpx.Client.request")
def test_sends_the_surface_it_is_given_and_leaves_the_422_to_the_server(
    mock_request, client
):
    mock_request.return_value = _error(422, "bad surface")
    with pytest.raises(SmartMemoryValidationError):
        client.get_next_upgrade_nudge(surface="studio")
    assert mock_request.call_args.kwargs["params"] == {"surface": "studio"}


@patch("httpx.Client.request")
def test_network_failure_is_the_base_client_error(mock_request, client):
    mock_request.side_effect = httpx.ConnectError("offline")
    with pytest.raises(SmartMemoryClientError):
        client.get_next_upgrade_nudge()
