"""Contract tests for the PLAT-PLUGIN-MARKETPLACE-1 H3 Python client surface: get_plugin_catalog()."""

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

BASE_URL = "http://localhost:9001"
CATALOG = {
    "generated_at": "2026-10-14T12:00:00Z",
    "tiles": [
        {
            "id": "basic_enricher",
            "axis": 3,
            "name": "basic_enricher",
            "status": "available",
            "plugin_type": "enricher",
            "stages": ["enrich"],
        }
    ],
    "refused": [],
}


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url=BASE_URL, api_key="test-token", workspace_id="workspace-test"
    )


def _response(
    status_code: int, json_data: dict | None = None, body: str = ""
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


class TestGetPluginCatalog:
    @patch("httpx.Client.request")
    def test_200_returns_the_body_from_the_catalog_url(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.return_value = _response(200, CATALOG)

        assert client.get_plugin_catalog() == CATALOG
        assert mock_request.call_args.args == (
            "GET",
            f"{BASE_URL}/memory/plugins/catalog",
        )
        assert not mock_request.call_args.kwargs["params"]
        assert (
            mock_request.call_args.kwargs["headers"]["Authorization"]
            == "Bearer test-token"
        )

    # One row per status the rule file requires, plus the 503 this endpoint returns when the registry cannot be read.
    ERROR_ROWS = [
        (400, SmartMemoryValidationError),
        (401, SmartMemoryPermissionError),
        (403, SmartMemoryPermissionError),
        (404, SmartMemoryNotFoundError),
        (500, SmartMemoryServerError),
        (503, SmartMemoryServerError),
    ]

    @pytest.mark.parametrize("status,exc_type", ERROR_ROWS)
    @patch("httpx.Client.request")
    def test_http_failure_raises_the_typed_error(
        self,
        mock_request: MagicMock,
        status: int,
        exc_type: type,
        client: SmartMemoryClient,
    ):
        mock_request.return_value = _response(status, body="failure detail")

        with pytest.raises(exc_type) as exc_info:
            client.get_plugin_catalog()
        assert exc_info.value.status_code == status
        assert "failure detail" in exc_info.value.detail

    @patch("httpx.Client.request")
    def test_transport_failure_raises_the_base_error(
        self, mock_request: MagicMock, client: SmartMemoryClient
    ):
        mock_request.side_effect = httpx.ConnectError("refused")

        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_plugin_catalog()
