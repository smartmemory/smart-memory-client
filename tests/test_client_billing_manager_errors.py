"""SVC-BILLING-ROLE-1 fix r1 (F1): HTTP errors through the public billing-manager methods raise typed exceptions.

One explicit row per case: (method, status, expected exception). Real ``_request``, only ``httpx.Client.request`` is mocked.
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

PERM, VALID, NOTFOUND, SERVER = (
    SmartMemoryPermissionError,
    SmartMemoryValidationError,
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
)

ROWS = [
    ("grant_billing_manager", 400, VALID),
    ("grant_billing_manager", 401, PERM),
    ("grant_billing_manager", 403, PERM),
    ("grant_billing_manager", 404, NOTFOUND),
    ("grant_billing_manager", 500, SERVER),
    ("revoke_billing_manager", 400, VALID),
    ("revoke_billing_manager", 401, PERM),
    ("revoke_billing_manager", 403, PERM),
    ("revoke_billing_manager", 404, NOTFOUND),
    ("revoke_billing_manager", 500, SERVER),
    ("list_billing_managers", 400, VALID),
    ("list_billing_managers", 401, PERM),
    ("list_billing_managers", 403, PERM),
    ("list_billing_managers", 404, NOTFOUND),
    ("list_billing_managers", 500, SERVER),
]


def _response(status: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = f"error {status}"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status} Error", request=MagicMock(spec=httpx.Request), response=resp
    )
    return resp


def _call(client: SmartMemoryClient, method: str):
    func = getattr(client, method)
    return func() if method == "list_billing_managers" else func("user_1")


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url="http://localhost:9001", api_key="test_token_abc123"
    )


@pytest.mark.parametrize(
    ("method", "status", "exception"), ROWS, ids=[f"{m}-{s}" for m, s, _ in ROWS]
)
@patch("httpx.Client.request")
def test_billing_manager_methods_raise_typed_errors(
    mock_request, client, method, status, exception
):
    mock_request.return_value = _response(status)
    with pytest.raises(exception) as exc:
        _call(client, method)
    assert exc.value.status_code == status
    assert isinstance(exc.value, SmartMemoryClientError)


@pytest.mark.parametrize(
    ("method", "payload"),
    [
        ("grant_billing_manager", {"user_id": "user_1", "listed": True}),
        ("revoke_billing_manager", {"user_id": "user_1", "listed": False}),
        ("list_billing_managers", {"user_ids": ["user_1"]}),
    ],
)
@patch("httpx.Client.request")
def test_billing_manager_methods_return_the_service_body(
    mock_request, client, method, payload
):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    mock_request.return_value = resp
    assert _call(client, method) == payload
