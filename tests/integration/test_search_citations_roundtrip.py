"""Integration round-trip test for RECALL-CITATIONS-1 — Python SDK search(cite=True).

Exercises the SDK end-to-end against a running smart-memory-service with
real backends (no mocks). Asserts that `client.last_citations` is populated
and that each citation references a returned result.

Run with: pytest tests/integration/test_search_citations_roundtrip.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.integration
class TestSearchCitationRoundTrip:
    """SDK search(cite=True) round-trip against the live service."""

    def test_search_cite_true_populates_last_citations(self, authenticated_client):
        client = authenticated_client
        tag = uuid.uuid4().hex[:8]

        for i in range(6):
            client.add(
                f"sdk citation roundtrip {tag} entry {i}",
                memory_type="semantic",
                use_pipeline=False,
            )

        results = client.search(f"sdk citation roundtrip {tag}", top_k=10, cite=True)

        # Caller still gets a flat list of MemoryItems
        assert isinstance(results, list)
        assert len(results) >= 1

        citations = client.last_citations
        assert isinstance(citations, list)
        assert len(citations) >= 1

        result_ids = {
            (r.item_id if hasattr(r, "item_id") else r["item_id"]) for r in results
        }
        for n, c in enumerate(citations, start=1):
            assert c["n"] == n
            assert c["footnote_marker"] == f"[^{n}]"
            assert c["item_id"] in result_ids

    def test_search_cite_false_leaves_last_citations_empty(self, authenticated_client):
        client = authenticated_client
        tag = uuid.uuid4().hex[:8]
        client.add(
            f"sdk no-cite roundtrip {tag}",
            memory_type="semantic",
            use_pipeline=False,
        )

        client.search(f"sdk no-cite roundtrip {tag}", top_k=5)
        assert client.last_citations == []
