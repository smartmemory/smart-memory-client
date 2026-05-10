"""Tests for RECALL-CITATIONS-1 — Python SDK search(cite=True)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from smartmemory_client import SmartMemoryClient


def _mock_response(json_payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload
    resp.headers = {"X-Search-Session-Id": "sess-test"}
    resp.raise_for_status = MagicMock()
    return resp


class TestSearchCite:
    def setup_method(self):
        self.client = SmartMemoryClient(
            base_url="http://localhost:9001",
            team_id="team-test",
            api_key="key-test",
        )

    def test_cite_false_returns_flat_list(self):
        items = [
            {
                "item_id": "id-1",
                "content": "alpha",
                "memory_type": "semantic",
                "score": 0.9,
            },
            {
                "item_id": "id-2",
                "content": "bravo",
                "memory_type": "semantic",
                "score": 0.8,
            },
        ]
        with patch(
            "smartmemory_client.client.httpx.request",
            return_value=_mock_response(items),
        ):
            results = self.client.search("anything")
        assert isinstance(results, list)
        assert len(results) == 2
        # last_citations is empty when cite was not requested
        assert self.client.last_citations == []

    def test_cite_true_unwraps_results_and_exposes_citations(self):
        wrapped = {
            "results": [
                {
                    "item_id": f"id-{i}",
                    "content": f"c-{i}",
                    "memory_type": "semantic",
                    "score": 1.0 - i * 0.1,
                }
                for i in range(5)
            ],
            "citations": [
                {
                    "n": 1,
                    "item_id": "id-0",
                    "item_type": "semantic",
                    "preview": "c-0",
                    "score": 1.0,
                    "footnote_marker": "[^1]",
                },
                {
                    "n": 2,
                    "item_id": "id-1",
                    "item_type": "semantic",
                    "preview": "c-1",
                    "score": 0.9,
                    "footnote_marker": "[^2]",
                },
                {
                    "n": 3,
                    "item_id": "id-2",
                    "item_type": "semantic",
                    "preview": "c-2",
                    "score": 0.8,
                    "footnote_marker": "[^3]",
                },
            ],
        }
        with patch(
            "smartmemory_client.client.httpx.request",
            return_value=_mock_response(wrapped),
        ) as mock_req:
            results = self.client.search("anything", cite=True)

        # Verify cite=true was sent in the body
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["cite"] is True

        # Caller still gets the flat list of MemoryItems
        assert isinstance(results, list)
        assert len(results) == 5

        # Citations available on the property
        cites = self.client.last_citations
        assert len(cites) == 3
        assert cites[0]["footnote_marker"] == "[^1]"
        assert cites[0]["item_id"] == "id-0"
        assert {
            "n",
            "item_id",
            "item_type",
            "preview",
            "score",
            "footnote_marker",
        } == set(cites[0].keys())

    def test_cite_true_no_results_returns_empty_citations(self):
        wrapped = {"results": [], "citations": []}
        with patch(
            "smartmemory_client.client.httpx.request",
            return_value=_mock_response(wrapped),
        ):
            results = self.client.search("no-hit", cite=True)
        assert results == []
        assert self.client.last_citations == []
