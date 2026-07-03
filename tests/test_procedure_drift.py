"""Tests for Procedure Schema Drift Detection (CFS-4) SDK methods.

Covers: list_drift_events, get_drift_event, resolve_drift_event,
sweep_drift, list_schema_snapshots.

Contract: contracts/procedure-drift.json
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient, SmartMemoryClientError

BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc123"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _ok_response(json_data: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = ""
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data
    return resp


def _error_response(status_code: int, body: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    request = MagicMock(spec=httpx.Request)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status_code} Error",
        request=request,
        response=resp,
    )
    resp.json.return_value = {}
    return resp


# ---------------------------------------------------------------------------
# list_drift_events
# ---------------------------------------------------------------------------
class TestListDriftEvents:
    @patch("httpx.Client.request")
    def test_defaults(self, mock_req, client):
        expected = {"workspace_id": "ws1", "record_count": 0, "records": []}
        mock_req.return_value = _ok_response(expected)
        result = client.list_drift_events()
        assert result == expected
        _, kwargs = mock_req.call_args
        assert kwargs["params"] == {"limit": 100}

    @patch("httpx.Client.request")
    def test_all_filters(self, mock_req, client):
        mock_req.return_value = _ok_response(
            {"workspace_id": "ws1", "record_count": 1, "records": [{}]}
        )
        client.list_drift_events(
            procedure_id="proc-1",
            resolved=False,
            breaking_only=True,
            start_date="2026-02-01",
            end_date="2026-02-13",
            limit=50,
        )
        _, kwargs = mock_req.call_args
        params = kwargs["params"]
        assert params["procedure_id"] == "proc-1"
        assert params["resolved"] is False
        assert params["breaking_only"] is True
        assert params["start_date"] == "2026-02-01"
        assert params["end_date"] == "2026-02-13"
        assert params["limit"] == 50

    @patch("httpx.Client.request")
    def test_none_params_omitted(self, mock_req, client):
        mock_req.return_value = _ok_response(
            {"workspace_id": "ws1", "record_count": 0, "records": []}
        )
        client.list_drift_events(procedure_id=None, resolved=None)
        _, kwargs = mock_req.call_args
        assert "procedure_id" not in kwargs["params"]
        assert "resolved" not in kwargs["params"]

    @patch("httpx.Client.request")
    def test_500_raises(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_drift_events()


# ---------------------------------------------------------------------------
# get_drift_event
# ---------------------------------------------------------------------------
class TestGetDriftEvent:
    @patch("httpx.Client.request")
    def test_happy_path(self, mock_req, client):
        expected = {
            "event_id": "evt-1",
            "procedure_id": "proc-1",
            "changes": [
                {
                    "path": "tools.search.properties.query",
                    "change_type": "removed",
                    "breaking": True,
                }
            ],
        }
        mock_req.return_value = _ok_response(expected)
        result = client.get_drift_event("evt-1")
        assert result == expected
        mock_req.assert_called_once()

    @patch("httpx.Client.request")
    def test_404_raises(self, mock_req, client):
        mock_req.return_value = _error_response(404, "Not found")
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_drift_event("nonexistent")

    @patch("httpx.Client.request")
    def test_500_raises(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.get_drift_event("evt-1")


# ---------------------------------------------------------------------------
# resolve_drift_event
# ---------------------------------------------------------------------------
class TestResolveDriftEvent:
    @patch("httpx.Client.request")
    def test_with_note(self, mock_req, client):
        expected = {"status": "resolved", "event_id": "evt-1", "resolved": True}
        mock_req.return_value = _ok_response(expected)
        result = client.resolve_drift_event(
            "evt-1", note="Schema updated intentionally"
        )
        assert result == expected
        _, kwargs = mock_req.call_args
        assert kwargs["json"] == {"note": "Schema updated intentionally"}

    @patch("httpx.Client.request")
    def test_without_note(self, mock_req, client):
        mock_req.return_value = _ok_response(
            {"status": "resolved", "event_id": "evt-1", "resolved": True}
        )
        client.resolve_drift_event("evt-1")
        _, kwargs = mock_req.call_args
        assert kwargs["json"] == {}

    @patch("httpx.Client.request")
    def test_404_raises(self, mock_req, client):
        mock_req.return_value = _error_response(404)
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.resolve_drift_event("nonexistent")

    @patch("httpx.Client.request")
    def test_400_raises(self, mock_req, client):
        mock_req.return_value = _error_response(400, "Bad request")
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.resolve_drift_event("evt-1", note="x" * 600)


# ---------------------------------------------------------------------------
# sweep_drift
# ---------------------------------------------------------------------------
class TestSweepDrift:
    @patch("httpx.Client.request")
    def test_happy_path(self, mock_req, client):
        expected = {
            "workspace_id": "ws1",
            "procedures_checked": 5,
            "drift_detected": 1,
            "events_created": 1,
        }
        mock_req.return_value = _ok_response(expected)
        result = client.sweep_drift()
        assert result == expected
        mock_req.assert_called_once()

    @patch("httpx.Client.request")
    def test_500_raises(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.sweep_drift()


# ---------------------------------------------------------------------------
# list_schema_snapshots
# ---------------------------------------------------------------------------
class TestListSchemaSnapshots:
    @patch("httpx.Client.request")
    def test_happy_path(self, mock_req, client):
        expected = {
            "workspace_id": "ws1",
            "procedure_id": "proc-1",
            "record_count": 2,
            "snapshots": [
                {
                    "snapshot_id": "snap-1",
                    "captured_at": "2026-02-10T08:00:00+00:00",
                    "tool_count": 3,
                },
                {
                    "snapshot_id": "snap-2",
                    "captured_at": "2026-02-12T08:00:00+00:00",
                    "tool_count": 4,
                },
            ],
        }
        mock_req.return_value = _ok_response(expected)
        result = client.list_schema_snapshots("proc-1")
        assert result == expected
        assert result["record_count"] == 2
        mock_req.assert_called_once()

    @patch("httpx.Client.request")
    def test_404_raises(self, mock_req, client):
        mock_req.return_value = _error_response(404)
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_schema_snapshots("nonexistent")

    @patch("httpx.Client.request")
    def test_500_raises(self, mock_req, client):
        mock_req.return_value = _error_response(500)
        with pytest.raises(SmartMemoryClientError, match="Request failed"):
            client.list_schema_snapshots("proc-1")
