"""Response decoding and typed conflict mapping follow the shared wire contract."""

import json
from smartmemory_client import RecallConflictError, SmartMemoryValidationError
from smartmemory_client.client import _exception_for_status
from smartmemory_client.models.memory_item import MemoryItem


def test_conflict_response_round_trip():
    conflict = {
        "with_item_ids": ["test_rcf_b"],
        "types": ["numeric_mismatch"],
        "ordering": "created_at_desc_item_id_asc",
    }
    item = MemoryItem.from_dict(
        {
            "item_id": "test_rcf_a",
            "content": "Acme permits 3 retries.",
            "conflict": conflict,
        }
    )
    assert item.conflict == conflict
    assert item.to_dict()["conflict"] == conflict
    assert "conflict" not in item.metadata
    assert MemoryItem.from_dict({"item_id": "test_rcf_alone"}).conflict is None


def test_only_recall_conflicts_get_the_recall_exception():
    detail = json.dumps(
        {
            "detail": {
                "error": "recall_conflict",
                "pairs": [["test_rcf_a", "test_rcf_b"]],
            }
        }
    )
    cls = _exception_for_status(409, detail)
    assert cls is RecallConflictError
    error = cls("Strict recall refused", status_code=409, detail=detail)
    assert isinstance(error, SmartMemoryValidationError)
    assert error.code == "recall_conflict"
    assert json.loads(error.detail)["detail"]["pairs"] == [["test_rcf_a", "test_rcf_b"]]
    assert (
        _exception_for_status(409, '{"detail":{"error":"revision_conflict"}}')
        is SmartMemoryValidationError
    )
    assert _exception_for_status(409, "not JSON") is SmartMemoryValidationError
