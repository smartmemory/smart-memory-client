"""Typed auth/session response shapes.

The service is migrating the session context from ``default_team_id`` to
``default_workspace_id``.  These types remain ordinary dictionaries at runtime
so existing callers can keep indexing responses without an API break.
"""

from typing import Any, Literal, TypedDict, cast


class SessionResponse(TypedDict, total=False):
    """Auth response fields shared by token refresh and ``/auth/me``.

    Session-context fields mirror AUTH-IDENTITY-MODEL-1.  Token and user fields
    are included because the two client methods return different envelopes.
    ``default_team_id`` is the one-release compatibility alias.
    """

    default_workspace_id: str
    active_workspace_id: str
    tenant_id: str
    tenant_role: Literal["owner", "admin", "member"]
    default_team_id: str

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int

    id: str
    email: str
    full_name: str | None
    subscription_tier: str
    is_active: bool
    is_verified: bool
    created_at: str
    roles: list[str]


def normalize_session_response(payload: dict[str, Any]) -> SessionResponse:
    """Return a dict-compatible session response with the preferred alias set.

    Older servers emit only ``default_team_id``.  Preserve every wire field and
    add ``default_workspace_id`` when necessary; when both are present, the new
    field is authoritative.
    """

    result = dict(payload)
    if not result.get("default_workspace_id") and result.get("default_team_id"):
        result["default_workspace_id"] = result["default_team_id"]
    return cast(SessionResponse, result)
