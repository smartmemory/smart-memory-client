"""Contract tests for the DIST-LITE-9 Python client surface (`POST /memory/ask`)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE_URL = "http://localhost:9001"
ASK_RESPONSE = {
    "answer": "No — Zed does not believe Yara stole the amulet.",
    "reasoning": "Zed trusts Yara and distrusts Xavier, who made the accusation.",
    "evidence": [
        {
            "item_id": "mem_amulet",
            "content": "Zed does not believe Yara stole the amulet.",
        }
    ],
    "relations": [
        {
            "source": "Zed",
            "type": "distrusts",
            "target": "Xavier",
            "source_id": "ent_zed",
            "target_id": "ent_xavier",
        },
        {
            "source": "Zed",
            "type": "trusts",
            "target": "Yara",
            "source_id": "ent_zed",
            "target_id": "ent_yara",
        },
    ],
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


class TestAsk:
    @patch("httpx.Client.request")
    def test_returns_the_full_contract_body_unchanged(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=ASK_RESPONSE)

        result = client.ask("Does Zed believe the amulet was stolen by Yara?")

        assert result == ASK_RESPONSE
        assert mock_request.call_args.args == ("POST", f"{BASE_URL}/memory/ask")
        assert mock_request.call_args.kwargs["json"] == {
            "question": "Does Zed believe the amulet was stolen by Yara?",
            "limit": 5,
        }

    @patch("httpx.Client.request")
    def test_limit_is_forwarded(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=ASK_RESPONSE)

        client.ask("who stole it", limit=12)

        assert mock_request.call_args.kwargs["json"]["limit"] == 12

    @patch("httpx.Client.request")
    def test_default_reasoning_is_not_sent_on_the_wire(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """The default must not become an explicit field — the two SDKs and the MCP
        backend all send the same body shape for the same call."""
        mock_request.return_value = _build_response(200, json_data=ASK_RESPONSE)

        client.ask("who stole it")

        assert "reasoning" not in mock_request.call_args.kwargs["json"]

    @patch("httpx.Client.request")
    def test_reasoning_false_is_forwarded(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=ASK_RESPONSE)

        client.ask("who stole it", reasoning=False)

        assert mock_request.call_args.kwargs["json"]["reasoning"] is False

    @patch("httpx.Client.request")
    def test_relations_carry_node_ids_for_graph_focus(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(200, json_data=ASK_RESPONSE)

        relations = client.ask("who trusts whom")["relations"]

        assert relations[0]["source_id"] == "ent_zed"
        assert relations[0]["target_id"] == "ent_xavier"

    @patch("httpx.Client.request")
    def test_bad_request_raises_validation_error(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(400, body="limit must be 1..50")

        with pytest.raises(SmartMemoryValidationError):
            client.ask("who stole it", limit=0)

    @patch("httpx.Client.request")
    def test_unanswerable_by_llm_raises_rather_than_returning_a_blank_answer(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(502, body="provider down")

        with pytest.raises(SmartMemoryServerError):
            client.ask("who stole it")

    @patch("httpx.Client.request")
    def test_server_error_raises(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(500, body="Internal Server Error")

        with pytest.raises(SmartMemoryServerError) as exc_info:
            client.ask("who stole it")
        assert exc_info.value.status_code == 500

    @patch("httpx.Client.request")
    def test_route_missing_raises_not_found(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        """A server that predates DIST-LITE-9 has no /memory/ask — that must surface as a
        404, not as a silent empty answer."""
        mock_request.return_value = _build_response(404, body="Not Found")

        with pytest.raises(SmartMemoryNotFoundError) as exc_info:
            client.ask("who stole it")
        assert exc_info.value.status_code == 404

    @patch("httpx.Client.request")
    def test_unauthorized_raises_permission_error(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _build_response(401, body="Unauthorized")

        with pytest.raises(SmartMemoryPermissionError):
            client.ask("who stole it")
