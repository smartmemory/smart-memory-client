"""Tests for the snapshot SDK methods (CORE-SUMMARY-1, E1).

Mirrors the project pattern in ``test_client_errors.py`` — mocked
``httpx.request`` so no server is required. Covers the canonical 200 /
404 / 4xx-error / 500 paths per the global ``error-coverage.md`` rule.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError


BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _resp(
    status_code: int, body: str = "", json_data: dict | list | None = None
) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.text = body
    if status_code >= 400:
        request = MagicMock(spec=httpx.Request)
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code} Error",
            request=request,
            response=r,
        )
    else:
        r.raise_for_status.return_value = None
    r.json.return_value = json_data if json_data is not None else {}
    return r


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPaths:
    @patch("httpx.Client.request")
    def test_summary_generate_returns_payload(self, mock_req, client):
        payload = {
            "snapshot_id": "snap_abc",
            "workspace_id": "ws_x",
            "trigger": "manual",
            "is_heartbeat": False,
        }
        mock_req.return_value = _resp(200, json_data=payload)

        out = client.summary_generate()
        assert out == payload
        # Verify the request shape
        call = mock_req.call_args
        assert call.args[0] == "POST"
        assert "/memory/summary/generate" in call.args[1]

    @patch("httpx.Client.request")
    def test_summary_latest_returns_payload(self, mock_req, client):
        mock_req.return_value = _resp(200, json_data={"snapshot_id": "snap_latest"})
        out = client.summary_latest()
        assert out == {"snapshot_id": "snap_latest"}

    @patch("httpx.Client.request")
    def test_summary_get_returns_payload(self, mock_req, client):
        mock_req.return_value = _resp(200, json_data={"snapshot_id": "snap_g"})
        out = client.summary_get("snap_g")
        assert out == {"snapshot_id": "snap_g"}

    @patch("httpx.Client.request")
    def test_summary_list_returns_array(self, mock_req, client):
        mock_req.return_value = _resp(
            200,
            json_data=[
                {"snapshot_id": "s1"},
                {"snapshot_id": "s2"},
            ],
        )
        out = client.summary_list(limit=2)
        assert len(out) == 2

    @patch("httpx.Client.request")
    def test_summary_delta_returns_payload(self, mock_req, client):
        mock_req.return_value = _resp(
            200,
            json_data={
                "from_snapshot_id": "a",
                "to_snapshot_id": "b",
                "entities_added": 3,
            },
        )
        out = client.summary_delta("a", "b")
        assert out["entities_added"] == 3

    @patch("httpx.Client.request")
    def test_summary_delete_returns_none_on_204(self, mock_req, client):
        # 204 — _request returns None
        r = MagicMock(spec=httpx.Response)
        r.status_code = 204
        r.raise_for_status.return_value = None
        r.text = ""
        mock_req.return_value = r

        # No exception, no return value expected
        client.summary_delete("snap_x")


# ---------------------------------------------------------------------------
# 404 — not found returns None for read methods, raises for delete
# ---------------------------------------------------------------------------


class TestNotFound:
    @patch("httpx.Client.request")
    def test_summary_latest_returns_none_on_404(self, mock_req, client):
        mock_req.return_value = _resp(404, body="No snapshots")
        assert client.summary_latest() is None

    @patch("httpx.Client.request")
    def test_summary_get_returns_none_on_404(self, mock_req, client):
        mock_req.return_value = _resp(404, body="not found")
        assert client.summary_get("nope") is None

    @patch("httpx.Client.request")
    def test_summary_delta_returns_none_on_404(self, mock_req, client):
        mock_req.return_value = _resp(404, body="not found")
        assert client.summary_delta("a", "b") is None

    @patch("httpx.Client.request")
    def test_summary_delete_raises_on_404(self, mock_req, client):
        mock_req.return_value = _resp(404, body="not found")
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.summary_delete("nope")


# ---------------------------------------------------------------------------
# Error paths — 4xx / 5xx surface as SmartMemoryClientError
# ---------------------------------------------------------------------------


class TestErrorPaths:
    @patch("httpx.Client.request")
    def test_summary_generate_409_lock_held(self, mock_req, client):
        mock_req.return_value = _resp(409, body='{"detail":{"reason":"lock_held"}}')
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.summary_generate()

    @patch("httpx.Client.request")
    def test_summary_delete_403_non_admin(self, mock_req, client):
        mock_req.return_value = _resp(403, body="Admin access required")
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.summary_delete("snap_x")

    @patch("httpx.Client.request")
    def test_summary_generate_500(self, mock_req, client):
        mock_req.return_value = _resp(500, body="Internal Server Error")
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.summary_generate()
