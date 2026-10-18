"""SVC-BILLING-MEMBERS-1: the SDK returns `members` and `billing_refusal` exactly as the service sent them.

One explicit row per case: (method, service body). Real ``_request``, only ``httpx.Client.request`` is mocked.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient

MEMBER = {
    "user_id": "user_1",
    "email": "ada@example.com",
    "name": "Ada",
    "is_admin": False,
    "listed": True,
}

LIST_ROWS = [
    ("admin_with_members", {"user_ids": ["user_1"], "members": [MEMBER]}),
    ("admin_with_no_other_members", {"user_ids": [], "members": []}),
    ("non_admin_has_no_members_key", {"user_ids": ["user_1"]}),
]

CURRENT_ROWS = [
    ("can_manage", {"can_manage_billing": True, "billing_refusal": ""}),
    ("api_key", {"can_manage_billing": False, "billing_refusal": "api_key"}),
    ("not_admin", {"can_manage_billing": False, "billing_refusal": "not_admin"}),
    ("comp", {"can_manage_billing": False, "billing_refusal": "comp"}),
    ("older_service_without_the_field", {"can_manage_billing": False}),
]


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url="http://localhost:9001", api_key="test_token_abc123"
    )


def _ok(body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = body
    return resp


@pytest.mark.parametrize(
    "body", [row[1] for row in LIST_ROWS], ids=[row[0] for row in LIST_ROWS]
)
@patch("httpx.Client.request")
def test_list_billing_managers_returns_the_body_unchanged(mock_request, client, body):
    mock_request.return_value = _ok(body)
    result = client.list_billing_managers()
    assert result == body
    assert ("members" in result) is ("members" in body)
    assert mock_request.call_args.args == (
        "GET",
        "http://localhost:9001/subscription/billing-managers",
    )


@pytest.mark.parametrize(
    "body", [row[1] for row in CURRENT_ROWS], ids=[row[0] for row in CURRENT_ROWS]
)
@patch("httpx.Client.request")
def test_get_subscription_returns_billing_refusal_unchanged(mock_request, client, body):
    mock_request.return_value = _ok(body)
    result = client.get_subscription()
    assert result == body
    assert result.get("billing_refusal") == body.get("billing_refusal")
    assert mock_request.call_args.args == (
        "GET",
        "http://localhost:9001/subscription/current",
    )
