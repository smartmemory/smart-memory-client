"""BUG-DECISION-HISTORY-PAGE-TIE-1 note H2 (Python client): the limit-2 cursor walk over a real service.

Frozen notes: ``smart-memory-ops/units/BUG-DECISION-HISTORY-PAGE-TIE-1/notes-frozen.md``. The service, its stores and
the 6-entry history (three entries at one instant) are prepared by the service-side driver of that unit, which writes
a seed file and serves the branch service over HTTP; ``SM_DV_HISTORY_SEED`` names that file. Without it the test skips.
"""

import json
import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def seed():
    path = os.environ.get("SM_DV_HISTORY_SEED")
    if not path or not os.path.exists(path):
        pytest.skip("SM_DV_HISTORY_SEED not set: no seeded service to walk")
    with open(path) as handle:
        return json.load(handle)


def test_h2_client_cursor_walk_returns_all_six_once_in_order(seed):
    from smartmemory_client import SmartMemoryClient
    from smartmemory_client import SmartMemoryValidationError

    with SmartMemoryClient(
        base_url=seed["base_url"], token=seed["token"], team_id=seed["workspace_id"]
    ) as client:
        whole = client.get_decision_history(seed["decision_id"], limit=500)["entries"]
        assert whole == seed["entries"] and len(whole) == 6
        walked, cursor = [], None
        for _ in range(10):
            page = client.get_decision_history(
                seed["decision_id"], limit=2, cursor=cursor
            )
            walked += page["entries"]
            if not page["truncated"]:
                assert page["next_cursor"] is None
                break
            cursor = page["next_cursor"]
        assert walked == whole
        with pytest.raises(SmartMemoryValidationError) as refused:
            client.get_decision_history(seed["decision_id"], cursor="garbage")
        assert refused.value.error_code == "invalid_cursor"
