"""Guard for a caller-supplied decision id placed in a request path (DECISION-RESTORE-ONE-ACTION-1 review fix M3).

The same rule as the MCP server's ``smartmemory_mcp/backends/path_guard.py``. The service runs uvicorn, which unquotes
the raw path before routing, so percent-encoding alone does not keep an id inside its own route, and an id equal to a
static sibling route needs no special character at all. ``path_id`` refuses, before any request is sent, every id that
could leave its route: anything with ``/`` or ``\\``, empty, ``.``, ``..``, control characters, and an id equal to a
static path segment the service has at that position. Everything else is percent-encoded as one segment (``?``,
``#``, ``%``, spaces), so a normal id is unchanged.
"""

from __future__ import annotations

import unicodedata
from typing import Any
from urllib.parse import quote

#: Static path segments the service has directly under each decision prefix an id follows (service OpenAPI snapshot;
#: the MCP list for the same prefixes). ``tests/test_decision_path_guard.py`` pins it to the MCP copy's values.
RESERVED_SEGMENTS: dict[str, frozenset[str]] = {
    "/memory/decisions/": frozenset({"create", "pending", "search"}),
    "/memory/decisions/pending/": frozenset({"create"}),
}


def path_id(value: Any, *, under: str) -> str:
    """``value`` as ONE safe path segment after the prefix ``under``; ValueError (no request made) otherwise."""
    reserved = RESERVED_SEGMENTS[under]
    text = "" if value is None else str(value)
    if text in ("", ".", ".."):
        raise ValueError(f"Invalid id {text!r}: it must name one item, not a path")
    if "/" in text or "\\" in text:
        raise ValueError(f"Invalid id {text!r}: an id cannot contain '/' or '\\'")
    if any(unicodedata.category(c) == "Cc" for c in text):
        raise ValueError(
            f"Invalid id {text!r}: an id cannot contain control characters"
        )
    if text in reserved:
        raise ValueError(
            f"Invalid id {text!r}: it is the name of another route under {under}"
        )
    return quote(text, safe="")


__all__ = ["RESERVED_SEGMENTS", "path_id"]
