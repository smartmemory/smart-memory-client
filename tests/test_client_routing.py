"""WS-ROUTING-2b: routing prefs, explain and the write echo (mocked transport, no live calls).

Wire shapes come from units/WS-ROUTING-2/report.md and
smart-memory-docs/docs/features/WS-ROUTING-1/ws-routing-contract.json.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryPermissionError,
    SmartMemoryRoutingConflictError,
    SmartMemoryValidationError,
    routing_echo,
)


def _ok(payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp


def _err(status: int, body):
    resp = MagicMock()
    resp.status_code = status
    resp.text = body if isinstance(body, str) else json.dumps(body)
    resp.headers = {}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=resp
    )
    return resp


def _client():
    return SmartMemoryClient(
        base_url="http://localhost:9001", team_id="team-test", api_key="key-test"
    )


def _call(client, response, fn):
    with patch.object(client._client, "request", return_value=response) as req:
        out = fn()
    return out, req


PREFS = {"account_default_workspace_id": "ws_1", "version": 3, "updated_at": "t"}


class TestPrefs:
    def test_get_no_row(self):
        c = _client()
        empty = {"account_default_workspace_id": None, "version": 0, "updated_at": None}
        out, req = _call(c, _ok(empty), c.get_routing_prefs)
        assert out == empty
        assert req.call_args.args[:2] == (
            "GET",
            "http://localhost:9001/memory/routing/prefs",
        )

    def test_set_sends_cas_body(self):
        c = _client()
        out, req = _call(c, _ok(PREFS), lambda: c.set_routing_prefs("ws_1", 2))
        assert out == PREFS
        assert req.call_args.args[:2] == (
            "PUT",
            "http://localhost:9001/memory/routing/prefs",
        )
        assert req.call_args.kwargs["json"] == {
            "account_default_workspace_id": "ws_1",
            "version": 2,
        }

    def test_set_none_clears(self):
        c = _client()
        _, req = _call(c, _ok(PREFS), lambda: c.set_routing_prefs(None, 0))
        assert req.call_args.kwargs["json"] == {
            "account_default_workspace_id": None,
            "version": 0,
        }

    @pytest.mark.parametrize("bad", [-1, 1.5, "1", None, True])
    def test_set_rejects_bad_version(self, bad):
        c = _client()
        with patch.object(c._client, "request") as req:
            with pytest.raises(ValueError):
                c.set_routing_prefs("ws_1", bad)
        req.assert_not_called()

    def test_cas_conflict_is_typed_and_catchable(self):
        c = _client()
        body = {"detail": {"error": "routing_prefs_version_conflict"}}
        with patch.object(c._client, "request", return_value=_err(409, body)):
            with pytest.raises(SmartMemoryRoutingConflictError) as ei:
                c.set_routing_prefs("ws_1", 1)
        e = ei.value
        assert isinstance(
            e, SmartMemoryValidationError
        )  # old `except` clauses still catch it
        assert (e.status_code, e.error_code) == (409, "routing_prefs_version_conflict")

    def test_conflict_then_reread_retry(self):
        c = _client()
        conflict = _err(409, {"detail": {"error": "routing_prefs_version_conflict"}})
        with patch.object(
            c._client, "request", side_effect=[conflict, _ok(PREFS), _ok(PREFS)]
        ) as req:
            try:
                c.set_routing_prefs("ws_1", 1)
            except SmartMemoryRoutingConflictError:
                fresh = c.get_routing_prefs()
                out = c.set_routing_prefs("ws_1", fresh["version"])
        assert out == PREFS
        assert req.call_args.kwargs["json"]["version"] == 3

    # One row per documented error shape (report.md PUT errors): status, body, class, code.
    @pytest.mark.parametrize(
        "status,body,cls,code",
        [
            (
                403,
                {"detail": {"error": "routing_prefs_human_only"}},
                SmartMemoryPermissionError,
                "routing_prefs_human_only",
            ),
            (
                409,
                {"detail": {"error": "client_bound_to_workspace"}},
                SmartMemoryValidationError,
                "client_bound_to_workspace",
            ),
            (
                403,
                {"detail": "insufficient_team_permissions"},
                SmartMemoryPermissionError,
                "insufficient_team_permissions",
            ),
            (
                422,
                {"detail": [{"loc": ["body", "rules"], "msg": "extra"}]},
                SmartMemoryValidationError,
                None,
            ),
            (422, "not json", SmartMemoryValidationError, None),
        ],
    )
    def test_error_shapes_surface_their_code(self, status, body, cls, code):
        c = _client()
        with patch.object(c._client, "request", return_value=_err(status, body)):
            with pytest.raises(cls) as ei:
                c.set_routing_prefs("ws_1", 1)
        assert ei.value.status_code == status
        assert ei.value.error_code == code
        assert not isinstance(ei.value, SmartMemoryRoutingConflictError)

    def test_409_with_other_code_is_not_a_cas_conflict(self):
        c = _client()
        with patch.object(
            c._client,
            "request",
            return_value=_err(409, {"detail": {"error": "workspace_locked"}}),
        ):
            with pytest.raises(SmartMemoryValidationError) as ei:
                c.set_routing_prefs("ws_1", 1)
        assert not isinstance(ei.value, SmartMemoryRoutingConflictError)
        assert ei.value.error_code == "workspace_locked"

    def test_get_error_also_carries_code(self):
        c = _client()
        with patch.object(
            c._client,
            "request",
            return_value=_err(403, {"detail": "insufficient_team_permissions"}),
        ):
            with pytest.raises(SmartMemoryClientError) as ei:
                c.get_routing_prefs()
        assert ei.value.error_code == "insufficient_team_permissions"


EXPLAIN = {
    "user_id": "u1",
    "workspace_id": "ws_1",
    "workspace_name": "Personal",
    "routed_by": "account_default",
    "routed_by_ref": None,
    "notices": [{"code": "c", "lever": "context", "detail": "d"}],
    "refusal": None,
    "candidates": [
        {
            "lever": "context",
            "workspace_id": None,
            "status": "inaccessible",
            "workspace_name": None,
        }
    ],
    "flags": {"personal_floor": False, "cookie_display_only": True},
}


class TestExplain:
    def test_no_args_sends_no_query(self):
        c = _client()
        out, req = _call(c, _ok(EXPLAIN), c.explain_routing)
        assert out == EXPLAIN
        assert req.call_args.args[:2] == (
            "GET",
            "http://localhost:9001/memory/routing/explain",
        )
        assert req.call_args.kwargs["params"] is None

    def test_all_args_go_as_query(self):
        c = _client()
        _, req = _call(
            c,
            _ok(EXPLAIN),
            lambda: c.explain_routing(
                client_key="mcp:cursor", context_key="repo:x", file_workspace_id="ws_9"
            ),
        )
        assert req.call_args.kwargs["params"] == {
            "client_key": "mcp:cursor",
            "context_key": "repo:x",
            "file_workspace_id": "ws_9",
        }

    def test_only_given_args_sent(self):
        c = _client()
        _, req = _call(c, _ok(EXPLAIN), lambda: c.explain_routing(context_key="k"))
        assert req.call_args.kwargs["params"] == {"context_key": "k"}

    def test_no_x_sm_client_header_without_a_hint(self):
        c = _client()
        _, req = _call(c, _ok(EXPLAIN), c.explain_routing)
        assert "X-SM-Client" not in req.call_args.kwargs["headers"]


ECHO = {
    "workspace_id": "ws_1",
    "workspace_name": "Personal",
    "routed_by": "call",
    "notices": [{"code": "x", "lever": "call", "detail": "y"}],
}


class TestWriteEcho:
    def test_add_detailed_returns_echo_and_add_still_returns_id(self):
        c = _client()
        resp = {"id": "item_1", **ECHO}
        out, req = _call(c, _ok(resp), lambda: c.add_detailed("hi", use_pipeline=False))
        assert out["id"] == "item_1"
        assert routing_echo(out) == ECHO
        assert req.call_args.kwargs["json"]["content"] == "hi"
        item_id, _ = _call(c, _ok(resp), lambda: c.add("hi"))
        assert item_id == "item_1"

    def test_old_server_reads_as_none(self):
        c = _client()
        out, _ = _call(c, _ok({"id": "item_1"}), lambda: c.add_detailed("hi"))
        assert routing_echo(out) == {
            "workspace_id": None,
            "workspace_name": None,
            "routed_by": None,
            "notices": [],
        }

    @pytest.mark.parametrize(
        "name,call,path",
        [
            ("ingest", lambda c: c.ingest("x"), "/memory/ingest"),
            ("ingest_full", lambda c: c.ingest_full("x"), "/memory/ingest/full"),
            (
                "ingest_conversation",
                lambda c: c.ingest_conversation([{"role": "user", "content": "x"}]),
                "/memory/ingest/conversation",
            ),
        ],
    )
    def test_ingest_results_carry_the_echo(self, name, call, path):
        c = _client()
        out, req = _call(c, _ok({"item_id": "i", **ECHO}), lambda: call(c))
        assert req.call_args.args[1] == f"http://localhost:9001{path}"
        assert out["item_id"] == "i"  # existing keys untouched
        assert SmartMemoryClient.routing_echo(out) == ECHO

    @pytest.mark.parametrize(
        "body", [None, [], "s", {"notices": "bad", "routed_by": None}]
    )
    def test_echo_never_raises(self, body):
        e = routing_echo(body)
        assert e["notices"] == [] and e["workspace_id"] is None
