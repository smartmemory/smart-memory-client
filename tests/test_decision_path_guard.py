"""Review fix M3 (DECISION-RESTORE-ONE-ACTION-1): a decision id can never send a request to another route.

Real request construction (httpx with a recording transport, no network): every client method that puts a decision id
in the path refuses an id that could leave its route before any request is made, and encodes every other id as one
segment. The rule matches the MCP server's ``path_id`` (pinned below)."""

from __future__ import annotations

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient
from smartmemory_client.path_guard import RESERVED_SEGMENTS

#: Every client method that puts a decision id in a request path, called with that id.
DECISION_ID_CALLS = {
    "get_decision": lambda c, i: c.get_decision(i),
    "supersede_decision": lambda c, i: c.supersede_decision(
        i, new_content="n", reason="r"
    ),
    "retract_decision": lambda c, i: c.retract_decision(i, reason="r"),
    "restore_decision": lambda c, i: c.restore_decision(i, reason="r"),
    "reinforce_decision": lambda c, i: c.reinforce_decision(i, evidence_id="e"),
    "link_decision_evidence": lambda c, i: c.link_decision_evidence(i, evidence_id="e"),
    "contradict_decision": lambda c, i: c.contradict_decision(i, evidence_id="e"),
    "get_decision_conflicts": lambda c, i: c.get_decision_conflicts(i),
    "get_provenance_chain": lambda c, i: c.get_provenance_chain(i),
    "get_causal_chain": lambda c, i: c.get_causal_chain(i),
    "resolve_requirement": lambda c, i: c.resolve_requirement(
        i, requirement_id="q", memory_id="m"
    ),
    "try_activate_decision": lambda c, i: c.try_activate_decision(i),
}


@pytest.fixture
def recorded():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(
            200,
            json={"decision_id": "d", "status": "active", "content": "c", "chain": []},
        )

    client = SmartMemoryClient(base_url="http://127.0.0.1:1", api_key="k")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, seen


def test_every_decision_id_path_refuses_an_id_that_leaves_its_route(recorded):
    client, seen = recorded
    for name, call in DECISION_ID_CALLS.items():
        for bad in (
            "victim/retract#",
            "..",
            ".",
            "",
            "a\\b",
            "a\nb",
            "search",
            "create",
            "pending",
        ):
            if name in ("resolve_requirement", "try_activate_decision") and bad in (
                "search",
                "pending",
            ):
                continue  # not a sibling route under /memory/decisions/pending/
            with pytest.raises(ValueError):
                call(client, bad)
    assert seen == []  # no request was ever sent


def test_a_normal_or_odd_id_stays_one_segment_of_its_own_route(recorded):
    client, seen = recorded
    for name, call in DECISION_ID_CALLS.items():
        seen.clear()
        try:
            call(client, "dec_1?x=1#frag %2F")
        except (
            Exception
        ):  # a response the method cannot parse is fine: the request is what is checked
            pass
        assert seen, name
        segment = "dec_1%3Fx%3D1%23frag%20%252F"
        assert f"/{segment}" in seen[0] and "?x=1" not in seen[0], (name, seen[0])
    assert RESERVED_SEGMENTS["/memory/decisions/"] == frozenset(
        {"create", "pending", "search", "auto-changes"}
    )
