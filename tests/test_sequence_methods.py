"""Contract tests for the SVC-ALLOC-1 Python client surface."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE_URL = "http://localhost:9001"
SEQUENCE_NAME = "compose:idea"
ALLOCATION = {"name": SEQUENCE_NAME, "value": 413, "first": 413, "count": 1}


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


def _sequence_error(reason: str) -> str:
    return json.dumps({"detail": {"reason": reason, "name": SEQUENCE_NAME}})


class TestAllocateSequence:
    @patch("httpx.Client.request")
    def test_allocate_returns_the_full_contract_body(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=ALLOCATION)

        assert client.allocate_sequence(SEQUENCE_NAME, floor=412) == ALLOCATION
        assert mock_request.call_args.args == (
            "POST",
            f"{BASE_URL}/memory/sequences/{SEQUENCE_NAME}/next",
        )
        assert mock_request.call_args.kwargs["json"] == {"floor": 412}

    @patch("httpx.Client.request")
    def test_omitted_options_send_an_empty_body(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """A bare allocate must not pin floor or count to a client-side default."""
        mock_request.return_value = _build_response(200, json_data=ALLOCATION)

        client.allocate_sequence(SEQUENCE_NAME)

        assert mock_request.call_args.kwargs["json"] == {}

    @patch("httpx.Client.request")
    def test_count_is_forwarded(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=ALLOCATION)

        client.allocate_sequence(SEQUENCE_NAME, count=10)

        assert mock_request.call_args.kwargs["json"] == {"count": 10}

    @patch("httpx.Client.request")
    def test_floor_zero_is_sent_not_dropped(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """`floor=0` is falsy but meaningful — an `if floor:` guard would eat it."""
        mock_request.return_value = _build_response(200, json_data=ALLOCATION)

        client.allocate_sequence(SEQUENCE_NAME, floor=0)

        assert mock_request.call_args.kwargs["json"] == {"floor": 0}

    @patch("httpx.Client.request")
    def test_503_raises_and_never_returns_a_value(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """Coordinator failure must never be mistaken for an allocation."""
        mock_request.return_value = _build_response(
            503, body=_sequence_error("coordinator_unavailable")
        )

        with pytest.raises(SmartMemoryServerError):
            client.allocate_sequence(SEQUENCE_NAME)

    @patch("httpx.Client.request")
    def test_429_quota_raises(self, mock_request: MagicMock, client: SmartMemoryClient):
        mock_request.return_value = _build_response(
            429, body=_sequence_error("sequence_quota_exceeded")
        )

        with pytest.raises(SmartMemoryClientError) as exc:
            client.allocate_sequence(SEQUENCE_NAME)
        assert exc.value.status_code == 429

    @patch("httpx.Client.request")
    def test_422_raises(self, mock_request: MagicMock, client: SmartMemoryClient):
        mock_request.return_value = _build_response(422, body='{"detail": []}')

        with pytest.raises(SmartMemoryValidationError):
            client.allocate_sequence(SEQUENCE_NAME)


class TestPeekSequence:
    @patch("httpx.Client.request")
    def test_peek_returns_the_current_value(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            200, json_data={"name": SEQUENCE_NAME, "value": 413}
        )

        assert client.peek_sequence(SEQUENCE_NAME) == 413
        assert mock_request.call_args.args == (
            "GET",
            f"{BASE_URL}/memory/sequences/{SEQUENCE_NAME}",
        )

    @patch("httpx.Client.request")
    def test_peek_unknown_sequence_returns_none(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            404, body=_sequence_error("sequence_not_found")
        )

        assert client.peek_sequence(SEQUENCE_NAME) is None

    @patch("httpx.Client.request")
    def test_peek_503_raises_rather_than_reporting_absence(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """A down coordinator is not the same answer as 'never allocated'."""
        mock_request.return_value = _build_response(
            503, body=_sequence_error("coordinator_unavailable")
        )

        with pytest.raises(SmartMemoryServerError):
            client.peek_sequence(SEQUENCE_NAME)
