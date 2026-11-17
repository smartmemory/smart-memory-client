"""STUDIO-DECISION-VIEW-1 U5: the three decision reads (history, sites, auto changes).

RECORDED responses, not a live service: the bodies follow the contract
(`smart-memory-docs` `STUDIO-DECISION-VIEW-1/decision-view-contract.json`) and the N17 answer the U4 report
(`report-u4-dv-service-common.md`) recorded through the real app. The refusals are the codes the routes name.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryClient,
    SmartMemoryNotFoundError,
    SmartMemoryValidationError,
)

HISTORY = {
    "decision_id": "d0",
    "entries": [
        {
            "entry_kind": "version",
            "at": "2026-10-01T09:00:00+00:00",
            "version": 2,
            "action": "supersede",
            "asked_by": "human:alice",
            "approved_by": None,
            "review_id": None,
            "reason": "capacity review Q4",
            "old_content": "Each site may enroll at most 15 participants.",
            "new_content": None,
            "related_decision_id": "d1",
            "related_visible": True,
            "evidence_id": None,
        },
    ],
    "start": {"at": "2026-09-01T09:00:00+00:00", "kind": "recorded", "note": "Recorded 1 Sep 2026."},
    "truncated": False,
}
SITES = {
    "decision_id": "d1",
    "at": "2026-10-15T00:00:00+00:00",
    "all_sites": False,
    "all_sites_from": None,
    "rows": [
        {
            "scope": {"site": "01"},
            "in_force": {"decision_id": "d1", "visible": True, "from": "2026-10-01T00:00:00+00:00"},
            "next": None,
        },
        {
            "scope": {"site": "03"},
            "in_force": {"decision_id": "d0", "visible": True, "from": "2026-09-01T00:00:00+00:00"},
            "next": {"decision_id": "d1", "visible": True, "from": "2026-11-01T00:00:00+00:00"},
        },
    ],
}
AUTO = {"items": [], "total": 0, "unchecked_count": 0, "notify": True, "supersession": "propose", "since": "2026-10-19T00:00:00+00:00"}


def _client(responder):
    calls = []
    client = SmartMemoryClient(base_url="https://sdk-test.invalid", api_key="synthetic")
    client._client.close()

    def answer(request):
        calls.append(request)
        return responder(request)

    client._client = httpx.Client(transport=httpx.MockTransport(answer))
    return client, calls


def _json(status, body):
    return lambda request: httpx.Response(status, json=body)


def test_history_reads_the_route_and_sends_only_what_is_set():
    client, calls = _client(_json(200, HISTORY))
    assert client.get_decision_history("d0") == HISTORY
    assert calls[0].method == "GET" and calls[0].url.path == "/memory/decisions/d0/history"
    assert dict(calls[0].url.params) == {}
    client.get_decision_history(
        "d0",
        limit=10,
        before="2026-11-01T00:00:00Z",
        as_of=datetime(2026, 10, 2, 8, tzinfo=timezone(timedelta(hours=8))),
    )
    assert dict(calls[1].url.params) == {
        "limit": "10",
        "before": "2026-11-01T00:00:00Z",
        "as_of": "2026-10-02T00:00:00+00:00",
    }


def test_sites_is_one_call_with_a_table_and_scopes_repeat():
    client, calls = _client(_json(200, SITES))
    answer = client.get_decision_sites(
        "d1", at="2026-10-15T00:00:00Z", scopes=[{"site": "05"}, {"site": "06"}]
    )
    assert len(calls) == 1 and calls[0].url.path == "/memory/decisions/d1/sites"
    assert calls[0].url.params.get_list("scope") == ['{"site":"05"}', '{"site":"06"}']
    assert calls[0].url.params["at"] == "2026-10-15T00:00:00Z"
    rows = {r["scope"]["site"]: r for r in answer["rows"]}
    assert rows["01"]["in_force"]["decision_id"] == "d1"
    assert rows["03"]["in_force"]["decision_id"] == "d0"
    assert rows["03"]["next"]["from"] == "2026-11-01T00:00:00+00:00"


def test_auto_changes_goes_to_the_literal_path_not_a_decision_id():
    client, calls = _client(_json(200, AUTO))
    assert client.list_decision_auto_changes() == AUTO
    assert calls[0].url.path == "/memory/decisions/auto-changes"
    assert dict(calls[0].url.params) == {}
    client.list_decision_auto_changes(status="all", limit=5, offset=10, since="2026-10-01T00:00:00Z")
    assert dict(calls[1].url.params) == {
        "status": "all",
        "limit": "5",
        "offset": "10",
        "since": "2026-10-01T00:00:00Z",
    }


@pytest.mark.parametrize("call", ["history", "sites"])
def test_unknown_decision_is_a_not_found_error(call):
    client, _ = _client(_json(404, {"detail": "Decision not found"}))
    with pytest.raises(SmartMemoryNotFoundError):
        if call == "history":
            client.get_decision_history("nope")
        else:
            client.get_decision_sites("nope")


@pytest.mark.parametrize(
    "call, code",
    [("history", "invalid_before"), ("sites", "invalid_scope"), ("auto", "invalid_status")],
)
def test_named_400_refusals_are_validation_errors_with_the_code(call, code):
    client, _ = _client(_json(400, {"detail": {"code": code, "message": "bad value"}}))
    with pytest.raises(SmartMemoryValidationError) as raised:
        if call == "history":
            client.get_decision_history("d0", before="x")
        elif call == "sites":
            client.get_decision_sites("d1", scopes=[{"site": "1"}])
        else:
            client.list_decision_auto_changes(status="x")
    assert raised.value.error_code == code


@pytest.mark.parametrize("bad", ["../x", "a/b", "auto-changes"])
def test_an_id_that_could_reach_another_route_is_refused_before_any_request(bad):
    client, calls = _client(_json(200, HISTORY))
    with pytest.raises(Exception):
        client.get_decision_history(bad)
    with pytest.raises(Exception):
        client.get_decision_sites(bad)
    assert calls == []
