"""Contract tests for the SVC-LEASE-1 Python client surface."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE_URL = "http://localhost:9001"
LEASE_KEY = "compose:write"
LEASE_TOKEN = "lease-token"
LEASE_GRANT = {
    "key": LEASE_KEY,
    "token": LEASE_TOKEN,
    "expires_at": "2026-08-05T12:00:30Z",
    "ttl_remaining_ms": 30000,
}


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url=BASE_URL,
        api_key="test-token",
        workspace_id="workspace-test",
    )


def _build_response(
    status_code: int, body: str = "", json_data: dict | None = None
) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = body
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code} Error",
            request=MagicMock(spec=httpx.Request),
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    response.json.return_value = json_data if json_data is not None else {}
    return response


def _lease_error(reason: str) -> str:
    return json.dumps({"detail": {"reason": reason, "key": LEASE_KEY}})


class TestLeaseMethods:
    @patch("httpx.Client.request")
    def test_acquire_200_returns_complete_grant(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=LEASE_GRANT)

        assert client.acquire_lease(LEASE_KEY, ttl_seconds=30) == LEASE_GRANT
        assert mock_request.call_args.args == (
            "POST",
            f"{BASE_URL}/memory/locks/{LEASE_KEY}",
        )
        assert mock_request.call_args.kwargs["json"] == {"ttl_seconds": 30}

    @patch("httpx.Client.request")
    def test_acquire_409_lock_held_returns_none(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body=_lease_error("lock_held"))

        assert client.acquire_lease(LEASE_KEY) is None

    @patch("httpx.Client.request")
    def test_acquire_503_raises_instead_of_returning_none(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            503, body=_lease_error("coordinator_unavailable")
        )

        with pytest.raises(SmartMemoryServerError):
            client.acquire_lease(LEASE_KEY)

    @patch("httpx.Client.request")
    def test_acquire_422_raises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(422, body='{"detail": []}')

        with pytest.raises(SmartMemoryValidationError):
            client.acquire_lease(LEASE_KEY)

    @patch("httpx.Client.request")
    def test_acquire_429_raises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            429, body=_lease_error("lease_quota_exceeded")
        )

        with pytest.raises(SmartMemoryClientError):
            client.acquire_lease(LEASE_KEY)

    @patch("httpx.Client.request")
    def test_renew_200_returns_grant_and_sends_token_header(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=LEASE_GRANT)

        assert client.renew_lease(LEASE_KEY, LEASE_TOKEN, ttl_seconds=45) == LEASE_GRANT
        assert mock_request.call_args.args == (
            "POST",
            f"{BASE_URL}/memory/locks/{LEASE_KEY}/renew",
        )
        assert mock_request.call_args.kwargs["json"] == {"ttl_seconds": 45}
        assert mock_request.call_args.kwargs["headers"]["X-Lease-Token"] == LEASE_TOKEN

    @patch("httpx.Client.request")
    def test_renew_409_not_owner_returns_none(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body=_lease_error("not_owner"))

        assert client.renew_lease(LEASE_KEY, LEASE_TOKEN) is None

    @patch("httpx.Client.request")
    def test_renew_503_raises_instead_of_returning_none(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            503, body=_lease_error("coordinator_unavailable")
        )

        with pytest.raises(SmartMemoryServerError):
            client.renew_lease(LEASE_KEY, LEASE_TOKEN)

    @patch("httpx.Client.request")
    def test_release_204_returns_true_and_sends_token_header(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(204)

        assert client.release_lease(LEASE_KEY, LEASE_TOKEN) is True
        assert mock_request.call_args.args == (
            "DELETE",
            f"{BASE_URL}/memory/locks/{LEASE_KEY}",
        )
        assert mock_request.call_args.kwargs["headers"]["X-Lease-Token"] == LEASE_TOKEN

    @patch("httpx.Client.request")
    def test_release_409_not_owner_returns_false(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body=_lease_error("not_owner"))

        assert client.release_lease(LEASE_KEY, LEASE_TOKEN) is False

    @patch("httpx.Client.request")
    def test_release_503_raises_instead_of_returning_false(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            503, body=_lease_error("coordinator_unavailable")
        )

        with pytest.raises(SmartMemoryServerError):
            client.release_lease(LEASE_KEY, LEASE_TOKEN)

    @patch("httpx.Client.request")
    def test_acquire_409_with_non_json_body_reraises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body="not valid json")

        with pytest.raises(SmartMemoryValidationError):
            client.acquire_lease(LEASE_KEY)


class TestLeaseWrongReasonReraises:
    """A 409 is only control flow when its reason is the one this call expects.

    Each method recognises exactly one reason. Any other 409 is an unmodelled
    server response, so it must surface rather than be flattened into the
    "definitively not ours" sentinel.
    """

    @patch("httpx.Client.request")
    def test_acquire_409_not_owner_reraises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body=_lease_error("not_owner"))

        with pytest.raises(SmartMemoryValidationError):
            client.acquire_lease(LEASE_KEY)

    @patch("httpx.Client.request")
    def test_renew_409_lock_held_reraises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body=_lease_error("lock_held"))

        with pytest.raises(SmartMemoryValidationError):
            client.renew_lease(LEASE_KEY, LEASE_TOKEN)

    @patch("httpx.Client.request")
    def test_release_409_lock_held_reraises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(409, body=_lease_error("lock_held"))

        with pytest.raises(SmartMemoryValidationError):
            client.release_lease(LEASE_KEY, LEASE_TOKEN)


class TestLeaseErrorCoverage:
    """Required by .claude/rules/error-coverage.md.

    Every public SDK method covers 500, and — because these routes are
    ``ScopePolicy.team_required`` — 401/403 as well.
    """

    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.acquire_lease(LEASE_KEY),
            lambda c: c.renew_lease(LEASE_KEY, LEASE_TOKEN),
            lambda c: c.release_lease(LEASE_KEY, LEASE_TOKEN),
        ],
        ids=["acquire", "renew", "release"],
    )
    @patch("httpx.Client.request")
    def test_server_error_raises(
        self, mock_request: MagicMock, client: SmartMemoryClient, call
    ):
        mock_request.return_value = _build_response(500, body="boom")

        with pytest.raises(SmartMemoryServerError) as exc_info:
            call(client)
        assert exc_info.value.status_code == 500

    @pytest.mark.parametrize("status", [401, 403])
    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.acquire_lease(LEASE_KEY),
            lambda c: c.renew_lease(LEASE_KEY, LEASE_TOKEN),
            lambda c: c.release_lease(LEASE_KEY, LEASE_TOKEN),
        ],
        ids=["acquire", "renew", "release"],
    )
    @patch("httpx.Client.request")
    def test_permission_error_raises(
        self, mock_request: MagicMock, client: SmartMemoryClient, call, status: int
    ):
        mock_request.return_value = _build_response(status, body="denied")

        with pytest.raises(SmartMemoryPermissionError) as exc_info:
            call(client)
        assert exc_info.value.status_code == status
