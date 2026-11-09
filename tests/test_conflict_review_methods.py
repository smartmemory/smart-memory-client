"""Tests for the conflict review queue and supersession policy SDK methods (OUTREACH-MARIUS-HITL-SURFACE-1)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)
from smartmemory_client.client import SmartMemoryClient

BASE = "http://localhost:9001"


@pytest.fixture
def client():
    return SmartMemoryClient(base_url=BASE, api_key="test-token", workspace_id="ws1")


def _ok(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _error(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "error"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status_code), request=MagicMock(), response=resp
    )
    return resp


SETTINGS = {
    "scope": "workspace",
    "scope_id": "ws1",
    "version": 3,
    "stated": {"review": {"supersession": "retire"}},
    "effective": {"review": {"supersession": "retire"}},
    "source": {"review": {"supersession": "workspace"}},
    "read_only": {},
}


class TestListConflictReviews:
    @patch("httpx.Client.request")
    def test_list_hits_the_route_with_paging(self, mock_req, client):
        mock_req.return_value = _ok(
            {
                "items": [{"id": "conflict_a"}],
                "status": "open",
                "limit": 50,
                "offset": 0,
            }
        )
        assert client.list_conflict_reviews()["items"][0]["id"] == "conflict_a"
        method, url = mock_req.call_args[0]
        assert (method, url) == ("GET", f"{BASE}/memory/reasoning/reviews")
        assert mock_req.call_args[1]["params"] == {
            "status": "open",
            "limit": 50,
            "offset": 0,
        }
        client.list_conflict_reviews(status="resolved", limit=10, offset=20)
        assert mock_req.call_args[1]["params"] == {
            "status": "resolved",
            "limit": 10,
            "offset": 20,
        }

    @pytest.mark.parametrize(
        ("status", "error"),
        [
            (403, SmartMemoryPermissionError),
            (422, SmartMemoryValidationError),
            (400, SmartMemoryValidationError),
            (500, SmartMemoryServerError),
        ],
    )
    @patch("httpx.Client.request")
    def test_list_errors_are_typed(self, mock_req, client, status, error):
        mock_req.return_value = _error(status)
        with pytest.raises(error):
            client.list_conflict_reviews()


class TestSettleConflictReview:
    @patch("httpx.Client.request")
    def test_settle_posts_action_and_reason_only(self, mock_req, client):
        mock_req.return_value = _ok(
            {"id": "conflict_a", "status": "resolved", "resolved_by": "api_key:u1"}
        )
        row = client.settle_conflict_review("conflict_a", "keep_b", "Checked the sheet")
        assert row["resolved_by"] == "api_key:u1"
        method, url = mock_req.call_args[0]
        assert (method, url) == (
            "POST",
            f"{BASE}/memory/reasoning/reviews/conflict_a/settle",
        )
        # The SDK never sends an actor: the server records the authenticated caller.
        assert mock_req.call_args[1]["json"] == {
            "action": "keep_b",
            "reason": "Checked the sheet",
        }

    @patch("httpx.Client.request")
    def test_settle_quotes_the_review_id(self, mock_req, client):
        mock_req.return_value = _ok({})
        client.settle_conflict_review("../../workspaces/x", "keep_a", "r")
        assert mock_req.call_args[0][1] == (
            f"{BASE}/memory/reasoning/reviews/..%2F..%2Fworkspaces%2Fx/settle"
        )

    @pytest.mark.parametrize(
        ("status", "error"),
        [
            (404, SmartMemoryNotFoundError),
            (409, SmartMemoryValidationError),
            (422, SmartMemoryValidationError),
            (403, SmartMemoryPermissionError),
            (500, SmartMemoryServerError),
        ],
    )
    @patch("httpx.Client.request")
    def test_settle_errors_are_typed(self, mock_req, client, status, error):
        mock_req.return_value = _error(status)
        with pytest.raises(error) as exc:
            client.settle_conflict_review("conflict_a", "keep_a", "r")
        assert exc.value.status_code == status


class TestSupersessionPolicy:
    @patch("httpx.Client.request")
    def test_get_reads_the_settings_knob(self, mock_req, client):
        mock_req.return_value = _ok(SETTINGS)
        assert client.get_supersession_policy() == {
            "workspace_id": "ws1",
            "policy": "retire",
            "source": "workspace",
            "stated": "retire",
            "version": 3,
        }
        method, url = mock_req.call_args[0]
        assert (method, url) == ("GET", f"{BASE}/memory/workspaces/ws1/settings")

    @pytest.mark.parametrize("policy", ["retire", "propose", None])
    @patch("httpx.Client.request")
    def test_set_patches_the_knob(self, mock_req, client, policy):
        mock_req.return_value = _ok(SETTINGS)
        client.set_supersession_policy(policy, workspace_id="ws9", if_match=3)
        method, url = mock_req.call_args[0]
        assert (method, url) == ("PATCH", f"{BASE}/memory/workspaces/ws9/settings")
        assert mock_req.call_args[1]["json"] == {
            "stated": {"review": {"supersession": policy}}
        }
        assert mock_req.call_args[1]["headers"]["If-Match"] == "3"

    @patch("httpx.Client.request")
    def test_set_rejects_an_unknown_policy_before_any_request(self, mock_req, client):
        with pytest.raises(ValueError):
            client.set_supersession_policy("delete")
        mock_req.assert_not_called()

    @pytest.mark.parametrize(
        ("status", "error"),
        [
            (403, SmartMemoryPermissionError),
            (400, SmartMemoryValidationError),
            (409, SmartMemoryValidationError),
            (404, SmartMemoryNotFoundError),
            (503, SmartMemoryServerError),
        ],
    )
    @patch("httpx.Client.request")
    def test_policy_errors_are_typed(self, mock_req, client, status, error):
        mock_req.return_value = _error(status)
        with pytest.raises(error):
            client.set_supersession_policy("propose")
        with pytest.raises(error):
            client.get_supersession_policy()
