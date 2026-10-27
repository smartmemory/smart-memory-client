"""Typed workspace-routing shapes (WS-ROUTING-2b).

Mirrors the three WS-ROUTING-2 service routes and the write echo, from
``smart-memory-docs/docs/features/WS-ROUTING-1/ws-routing-contract.json``. Like
``SessionResponse`` these are plain dicts at runtime, so existing callers keep
indexing responses. Every echo field is optional: an older server omits them and
that reads as ``None``, never an error. ``routed_by_ref`` is never echoed.
"""

from typing import Any, Literal, TypedDict

RoutedBy = Literal[
    "call",
    "bound_key",
    "session",
    "context",
    "client_default",
    "account_default",
    "rule",
    "migration",
    "sync",
    "system",
]


class RoutingNotice(TypedDict, total=False):
    code: str
    lever: str
    detail: str


class RoutingEcho(TypedDict):
    """Where a write landed. All ``None``/empty when the server predates routing."""

    workspace_id: str | None
    workspace_name: str | None
    routed_by: RoutedBy | None
    notices: list[RoutingNotice]


class RoutingPrefs(TypedDict):
    """``GET``/``PUT /memory/routing/prefs``. No stored row reads ``{None, 0, None}``."""

    account_default_workspace_id: str | None
    version: int
    updated_at: str | None


class RoutingCandidate(TypedDict, total=False):
    lever: str
    workspace_id: str | None
    status: str
    workspace_name: str | None


class RoutingFlags(TypedDict, total=False):
    personal_floor: bool
    cookie_display_only: bool


class RoutingExplain(TypedDict, total=False):
    """``GET /memory/routing/explain``. ``routed_by_ref`` is returned only to the
    item author and workspace admins, so treat it as optional."""

    user_id: str
    workspace_id: str | None
    workspace_name: str | None
    routed_by: RoutedBy | None
    routed_by_ref: str | None
    notices: list[RoutingNotice]
    refusal: str | None
    candidates: list[RoutingCandidate]
    flags: RoutingFlags


def routing_echo(result: Any) -> RoutingEcho:
    """Read the write echo off an add/ingest response.

    Accepts the response dict (or ``None``). Missing keys, an old server, a
    non-dict body and a non-list ``notices`` all read as ``None``/``[]``.
    """

    data = result if isinstance(result, dict) else {}
    notices = data.get("notices")
    return {
        "workspace_id": data.get("workspace_id"),
        "workspace_name": data.get("workspace_name"),
        "routed_by": data.get("routed_by"),
        "notices": list(notices) if isinstance(notices, list) else [],
    }
