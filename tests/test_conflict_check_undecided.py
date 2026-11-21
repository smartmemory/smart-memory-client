"""BUG-FAIL-IF-CONFLICTED-SOURCE-DATE-1: the "could not decide" 409 becomes its own typed error, and the marker shows.

The bodies are the service's real answers for frozen pair 4 (``units/BUG-FAIL-IF-CONFLICTED-SOURCE-DATE-1/
wire-bodies.log``, captured from the real routes over a real Lite core). They run through a real ``httpx`` client on a
``MockTransport``, so status handling, ``raise_for_status`` and the JSON decode are the real ones.
"""

import json

import httpx
import pytest

from smartmemory_client import (
    ConflictCheckUndecidedError,
    RecallConflictError,
    SmartMemoryClient,
    SmartMemoryValidationError,
)
from smartmemory_client.client import _exception_for_status

REASON = (
    "two different values for one attribute of a shared identifier; "
    "the aligned-text check could not compare them"
)
UNDECIDED_409 = {
    "detail": {
        "error": "conflict_check_undecided",
        "message": f"Recall conflict check could not decide 1 pair(s): {REASON}",
        "pairs": [["test_ccu_a", "test_ccu_b"]],
        "reason": REASON,
    }
}
MARKER = {
    "method": "aligned_text",
    "undecided_pairs": [{"item_ids": ["test_ccu_a", "test_ccu_b"], "reason": REASON}],
}
ITEMS = [
    {"item_id": "test_ccu_a", "content": "KX-410 costs 1,200 EUR.", "conflict": None},
    {"item_id": "test_ccu_b", "content": "KX-410 price is 1,450 EUR.", "conflict": None},
]


def _client(handler):
    client = SmartMemoryClient(base_url="http://testserver", team_id="team-test", api_key="key-test")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_only_the_undecided_409_gets_the_undecided_exception():
    detail = json.dumps(UNDECIDED_409)
    cls = _exception_for_status(409, detail)
    assert cls is ConflictCheckUndecidedError
    assert issubclass(cls, SmartMemoryValidationError)
    assert not issubclass(cls, RecallConflictError)
    recall = json.dumps({"detail": {"error": "recall_conflict", "pairs": [["a", "b"]]}})
    assert _exception_for_status(409, recall) is RecallConflictError
    assert _exception_for_status(409, '{"detail":{"error":"revision_conflict"}}') is SmartMemoryValidationError
    assert _exception_for_status(409, "not JSON") is SmartMemoryValidationError


def test_search_raises_the_typed_error_with_pairs_and_reason():
    client = _client(lambda request: httpx.Response(409, json=UNDECIDED_409))
    with pytest.raises(ConflictCheckUndecidedError) as raised:
        client.search("KX-410", fail_if_conflicted=True)
    error = raised.value
    assert error.status_code == 409
    assert error.code == "conflict_check_undecided"
    assert error.pairs == [["test_ccu_a", "test_ccu_b"]]
    assert error.reason == REASON
    assert not isinstance(error, RecallConflictError)


def test_search_exposes_the_marker_and_clears_it_on_the_next_call():
    bodies = iter(
        [
            {"results": ITEMS, "group_roots": {}, "conflict_check": MARKER},
            {"results": ITEMS, "group_roots": {}},
        ]
    )
    client = _client(lambda request: httpx.Response(200, json=next(bodies)))
    items = client.search("KX-410", fail_if_conflicted=True)
    assert [i.item_id for i in items] == ["test_ccu_a", "test_ccu_b"]
    assert all(i.conflict is None for i in items)
    assert client.last_conflict_check == MARKER
    client.search("KX-410")
    assert client.last_conflict_check is None


def test_recall_pack_raises_the_typed_error_and_returns_the_manifest_marker():
    answers = iter(
        [
            httpx.Response(409, json=UNDECIDED_409),
            httpx.Response(200, json={"block": "b", "conflict": False, "manifest": {"conflict_check": MARKER}}),
        ]
    )
    client = _client(lambda request: next(answers))
    sections = [{"name": "tier1_user", "cap_tokens": 2000}]
    with pytest.raises(ConflictCheckUndecidedError) as raised:
        client.recall_pack(2000, sections=sections, fail_if_conflicted=True)
    assert raised.value.pairs == [["test_ccu_a", "test_ccu_b"]]
    pack = client.recall_pack(2000, sections=sections, fail_if_conflicted=True)
    assert pack["manifest"]["conflict_check"] == MARKER
    assert pack["conflict"] is False
