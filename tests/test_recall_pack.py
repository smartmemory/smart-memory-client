"""Contract tests for the CORE-RECALL-BUDGET-1 Python client surface."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE_URL = "http://localhost:9001"
RECALL_PACK = {
    "block": "## active_plan\n...\n## snapshot\n...",
    "manifest": {
        "budget_tokens": 4000,
        "used_tokens": 2100,
        "tokenizer": "heuristic:chars/4",
        "query": "what did we decide about auth?",
        "sections": [
            {
                "name": "active_plan",
                "cap_tokens": 400,
                "used_tokens": 350,
                "items_packed": 1,
                "items_compacted": 0,
                "items_dropped": 0,
            },
            {
                "name": "snapshot",
                "cap_tokens": 800,
                "used_tokens": 750,
                "items_packed": 1,
                "items_compacted": 1,
                "items_dropped": 0,
            },
        ],
    },
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


class TestRecallPack:
    @patch("httpx.Client.request")
    def test_returns_the_full_contract_body_unchanged(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=RECALL_PACK)

        result = client.recall_pack(4000, query="what did we decide about auth?")

        assert result == RECALL_PACK
        assert mock_request.call_args.args == (
            "POST",
            f"{BASE_URL}/memory/recall/pack",
        )
        assert mock_request.call_args.kwargs["json"] == {
            "budget_tokens": 4000,
            "query": "what did we decide about auth?",
        }

    @patch("httpx.Client.request")
    def test_omitted_query_and_sections_are_not_sent(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=RECALL_PACK)

        client.recall_pack(4000)

        assert mock_request.call_args.kwargs["json"] == {"budget_tokens": 4000}

    @patch("httpx.Client.request")
    def test_sections_are_forwarded(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=RECALL_PACK)
        sections = [{"name": "active_plan", "cap_tokens": 400}]

        client.recall_pack(4000, sections=sections)

        assert mock_request.call_args.kwargs["json"] == {
            "budget_tokens": 4000,
            "sections": sections,
        }

    @patch("httpx.Client.request")
    def test_wakeup_preset_is_forwarded(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """Phase 5: the session-start L1 card is a param on this call, not a new endpoint."""
        mock_request.return_value = _build_response(200, json_data=RECALL_PACK)

        client.recall_pack(200, preset="wakeup")

        assert mock_request.call_args.kwargs["json"] == {
            "budget_tokens": 200,
            "preset": "wakeup",
        }

    @patch("httpx.Client.request")
    def test_omitted_preset_is_not_sent(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """An absent preset must not become an explicit null on the wire — the SDKs, the
        MCP remote backend and this client all send the same body shape."""
        mock_request.return_value = _build_response(200, json_data=RECALL_PACK)

        client.recall_pack(4000, query="auth")

        assert "preset" not in mock_request.call_args.kwargs["json"]

    @patch("httpx.Client.request")
    def test_400_invalid_budget_raises_validation_error(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(
            400, body='{"detail": "invalid budget_tokens"}'
        )

        with pytest.raises(SmartMemoryValidationError):
            client.recall_pack(0)

    @patch("httpx.Client.request")
    def test_500_raises_server_error(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(500, body="boom")

        with pytest.raises(SmartMemoryServerError):
            client.recall_pack(4000)
