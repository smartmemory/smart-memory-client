"""Pin Python SDK search and serialization to CORE-RERANK-EXPOSE-1."""

import json
from pathlib import Path
from typing import get_args
from unittest.mock import Mock, patch

import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client.models.memory_item import MemoryItem, RerankStatus

CONTRACT = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / (
            "smart-memory-docs/docs/features/CORE-RERANK-EXPOSE-1/rerank-exposure-contract.json"
        )
    ).read_text()
)


def evidence(status: str, score: float = -11.4) -> dict:
    """An HTTP item with all contract fields, including diagnostics from a larger pool."""
    return {
        "item_id": status,
        "content": "Python web frameworks",
        "score": 0.8,
        "rerank_score": score if status == "scored" else None,
        "rerank_status": status,
        "rerank_model": {
            "name": "actual-model",
            "revision": "revision",
            "activation": "Identity",
        },
        "rerank_pool_size": 30,
        "rerank_candidate_count": 25,
        "rerank_scored_count": 25,
        "rerank_pool_capped": True,
        "rerank_max_doc_chars": 512,
    }


def test_enum_and_fields_match_contract():
    assert (
        list(get_args(RerankStatus)) == CONTRACT["properties"]["rerank_status"]["enum"]
    )
    fields = {
        key for key in MemoryItem.__dataclass_fields__ if key.startswith("rerank_")
    }
    assert fields == set(CONTRACT["required"])


@pytest.mark.parametrize(
    "expertise,cite", [(False, False), (False, True), (True, False), (True, True)]
)
def test_search_keeps_all_reasons_and_evidence(expertise, cite):
    rows = [
        evidence(status) for status in CONTRACT["properties"]["rerank_status"]["enum"]
    ]
    response = Mock(status_code=200, headers={})
    response.json.return_value = {
        "results": {"semantic": rows} if expertise else rows,
        "citations": [],
    }
    client = SmartMemoryClient(base_url="http://test", team_id="test", api_key="fake")
    with patch("httpx.Client.request", return_value=response):
        results = client.search("Python", expertise=expertise, cite=cite)
    if expertise:
        results = results["semantic"]
    assert [item.item_id for item in results] == [row["item_id"] for row in rows]
    for item, row in zip(results, rows, strict=True):
        for key in CONTRACT["required"]:
            assert item[key] == row[key] == item.to_dict()[key]
        assert item.score == 0.8


@pytest.mark.parametrize("score", [-11.4, 0.0, 6.5])
def test_raw_scores_are_not_normalized(score):
    item = MemoryItem.from_dict(evidence("scored", score))
    assert item.rerank_score == score and item.rerank_status == "scored"


def test_older_server_is_explicitly_unverified(caplog):
    item = MemoryItem.from_dict({"item_id": "old", "content": "legacy", "score": 1.0})
    assert item.rerank_score is None and item.rerank_status == "not_reranked"
    assert item.rerank_model is None and item.rerank_candidate_count is None
    assert "rerank_status=not_reranked" in caplog.text
