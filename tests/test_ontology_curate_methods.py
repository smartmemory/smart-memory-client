"""Tests for ontology curation queue client SDK methods (ONTO-HITL-CURATE-1)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import SmartMemoryNotFoundError, SmartMemoryValidationError
from smartmemory_client.client import SmartMemoryClient


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


@pytest.fixture
def mock_response():
    def _make(json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    return _make


def _error_response(status_code, text="error"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status_code), request=MagicMock(), response=resp
    )
    return resp


def _assert_post(mock_req, path, body):
    call = mock_req.call_args
    assert call[0][0] == "POST"
    assert call[0][1] == f"http://localhost:9001{path}"
    assert call[1]["json"] == body


class TestListOntologyReviewQueue:
    @patch("httpx.Client.request")
    def test_list_defaults(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {"items": [{"id": "Candidate", "status": "open"}], "next_cursor": None}
        )
        result = client.list_ontology_review_queue()

        assert result["items"][0]["id"] == "Candidate"
        call = mock_req.call_args
        assert call[0][0] == "GET"
        assert call[0][1] == "http://localhost:9001/memory/ontology/queue"
        assert call[1]["params"] == {"limit": 100}

    @patch("httpx.Client.request")
    def test_list_with_all_filters(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"items": [], "next_cursor": "next-1"})
        client.list_ontology_review_queue(
            tier="working",
            assignee="alice",
            source="llm",
            limit=25,
            cursor="cursor-1",
        )

        call = mock_req.call_args
        assert call[0][1] == "http://localhost:9001/memory/ontology/queue"
        assert call[1]["params"] == {
            "limit": 25,
            "tier": "working",
            "assignee": "alice",
            "source": "llm",
            "cursor": "cursor-1",
        }


class TestOntologyReviewActions:
    @patch("httpx.Client.request")
    def test_approve_with_expected_tier(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"ok": True})
        result = client.approve_ontology_type("Needs/Review", expected_tier="working")

        assert result == {"ok": True}
        _assert_post(
            mock_req,
            "/memory/ontology/queue/Needs%2FReview/approve",
            {"expected_tier": "working"},
        )

    @patch("httpx.Client.request")
    def test_reject_omits_expected_tier(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"ok": True})
        client.reject_ontology_type("Needs Review")

        _assert_post(mock_req, "/memory/ontology/queue/Needs%20Review/reject", {})

    @patch("httpx.Client.request")
    def test_merge_with_expected_tier(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"ok": True})
        client.merge_ontology_review_type(
            "Candidate",
            "Canonical",
            expected_tier="proposed",
        )

        _assert_post(
            mock_req,
            "/memory/ontology/queue/Candidate/merge",
            {"into_id": "Canonical", "expected_tier": "proposed"},
        )

    @patch("httpx.Client.request")
    def test_edit_promote_omits_expected_tier(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"ok": True})
        client.edit_promote_ontology_type("Candidate", {"name": "Canonical"})

        _assert_post(
            mock_req,
            "/memory/ontology/queue/Candidate/edit-promote",
            {"edits": {"name": "Canonical"}},
        )

    @patch("httpx.Client.request")
    def test_assign_reviewer_allows_clear(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"ok": True})
        client.assign_ontology_review("Candidate", None)

        _assert_post(
            mock_req,
            "/memory/ontology/queue/Candidate/assign",
            {"assignee": None},
        )

    @patch("httpx.Client.request")
    def test_retire_confirmed_type(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response({"ok": True})
        result = client.retire_ontology_type("confirmed/private", "superseded")

        assert result == {"ok": True}
        _assert_post(
            mock_req,
            "/memory/ontology/types/confirmed%2Fprivate/retire",
            {"reason": "superseded"},
        )


class TestBulkOntologyReviewAction:
    @patch("httpx.Client.request")
    def test_bulk_returns_mixed_report(self, mock_req, client, mock_response):
        mock_req.return_value = mock_response(
            {
                "results": [
                    {"id": "Candidate", "ok": True, "error": None},
                    {"id": "Missing", "ok": False, "error": "not found"},
                ]
            }
        )
        result = client.bulk_ontology_review_action(
            "merge",
            ["Candidate", "Missing"],
            params={"into_id": "Canonical"},
            expected_tier="working",
        )

        assert result["results"][0]["ok"] is True
        assert result["results"][1]["error"] == "not found"
        _assert_post(
            mock_req,
            "/memory/ontology/queue/bulk",
            {
                "action": "merge",
                "ids": ["Candidate", "Missing"],
                "params": {"into_id": "Canonical"},
                "expected_tier": "working",
            },
        )


class TestOntologyReviewErrors:
    @patch("httpx.Client.request")
    def test_approve_not_found_404(self, mock_req, client):
        mock_req.return_value = _error_response(404, "not found")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.approve_ontology_type("Missing")
        assert exc.value.status_code == 404

    @patch("httpx.Client.request")
    def test_reject_tier_mismatch_409(self, mock_req, client):
        mock_req.return_value = _error_response(409, "expected_tier mismatch")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.reject_ontology_type("Candidate", expected_tier="working")
        assert exc.value.status_code == 409

    @patch("httpx.Client.request")
    def test_edit_promote_invalid_edits_400(self, mock_req, client):
        mock_req.return_value = _error_response(400, "invalid edits")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.edit_promote_ontology_type("Candidate", {"tier": "invalid"})
        assert exc.value.status_code == 400
