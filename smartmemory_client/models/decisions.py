"""Typed decision reply shapes.

``DecisionActivation`` mirrors ``POST /memory/decisions/pending/{decision_id}/activate``, from
``smart-memory-docs/docs/plans/contracts/decisions.json`` ``api.activate_response``
(BUG-MCP-ACTIVATE-STAGED-REASON-1). A plain dict at runtime, so existing callers keep
indexing responses.
"""

from typing import Any, Literal, NotRequired, TypedDict

#: The values ``reason`` may carry today. A newer server may send another: treat an
#: unknown value as no reason.
ActivationReason = Literal["staged"]


class DecisionActivation(TypedDict):
    """The activate reply.

    ``reason`` is present only when ``activated`` is false and the caller may be told why.
    ``"staged"``: an approved rule change stored but not yet published; only its
    approval's publish puts it in force. Absent for a missing id, an id the caller may
    not see, and every other state (never ``None``).
    """

    activated: bool
    decision: dict[str, Any] | None
    reason: NotRequired[ActivationReason]
