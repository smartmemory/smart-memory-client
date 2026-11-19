"""DECISION-DOOR-1 shape (b): the service's 409 ``decision_history_protected`` reaches the caller typed.

Body as the service sends it (``memory_service/utils/decision_history_errors.py``). ``update()`` must not turn it into a
save conflict (a retry with the same key would be refused again, and the old path logged "scoped conflict code lost").
"""

import json

import pytest

from smartmemory_client import DecisionHistoryProtectedError, SmartMemoryClient
from smartmemory_client.client import _exception_for_status
from smartmemory_client.errors import SaveConflictError

BODY = json.dumps(
    {
        "detail": {
            "error_code": "decision_history_protected",
            "error": "decision_history_protected",
            "message": "A decision's history ... was not applied.",
        }
    }
)


def test_the_409_maps_to_the_typed_error():
    assert _exception_for_status(409, BODY) is DecisionHistoryProtectedError
    assert DecisionHistoryProtectedError.error_code == "decision_history_protected"


def test_update_raises_it_not_a_save_conflict(monkeypatch):
    client = SmartMemoryClient(base_url="http://test", api_key="k", workspace_id="w")

    def refused(method, path, **kwargs):
        raise _exception_for_status(409, BODY)("refused", status_code=409, detail=BODY)

    monkeypatch.setattr(client, "_request", refused)
    with pytest.raises(DecisionHistoryProtectedError) as caught:
        client.update("dec_1", metadata={"status": "superseded"})
    assert not isinstance(caught.value, SaveConflictError)
