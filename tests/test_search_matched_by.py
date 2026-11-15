"""CLAIMS-21-FIX1 (review M2): search results keep ``matched_by``, the lanes that found each result."""

from unittest.mock import Mock, patch

import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client.models.memory_item import MemoryItem


def _search(rows, **options):
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"results": rows, "citations": []}
    client = SmartMemoryClient(base_url="http://test", team_id="test", api_key="fake")
    with patch("httpx.Client.request", return_value=response):
        return client.search("atlas budget", **options)


@pytest.mark.parametrize("cite", [False, True], ids=["plain", "cited"])
def test_search_results_carry_the_lanes_that_found_them(cite):
    rows = [
        {
            "item_id": "test_mb_both",
            "content": "a",
            "score": 0.9,
            "matched_by": ["lexical", "semantic"],
        },
        {
            "item_id": "test_mb_one",
            "content": "b",
            "score": 0.4,
            "matched_by": ["semantic"],
        },
        {
            "item_id": "test_mb_unrecorded",
            "content": "c",
            "score": 0.2,
            "matched_by": None,
        },
    ]
    results = _search(rows, cite=cite)
    assert [item.matched_by for item in results] == [
        ["lexical", "semantic"],
        ["semantic"],
        None,
    ]
    assert (
        results[0]["matched_by"]
        == results[0].to_dict()["matched_by"]
        == ["lexical", "semantic"]
    )
    assert results[0].score == 0.9


def test_an_older_server_without_the_field_reads_as_not_recorded():
    item = MemoryItem.from_dict(
        {"item_id": "test_mb_old", "content": "x", "score": 0.5}
    )
    assert item.matched_by is None
    assert "matched_by" not in item.metadata
