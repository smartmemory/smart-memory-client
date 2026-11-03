"""WEB-VECTOR-SEARCH-TAB-1 (VEC-TAB-U4): ``vector_query/stats/inspect/missing``.

Real ``_request``, only ``httpx.Client.request`` is mocked. Routes, parameters and
error statuses are the contract's (smart-memory-docs
``docs/features/WEB-VECTOR-SEARCH-TAB-1/vector-contract.json``). No live server.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemorySubstrateError,
    SmartMemoryUnsupportedError,
)
from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

SPACE = {"collection": "memory", "model_id": "m", "dimension": 4}
PREVIEW = [0.1] * 16
HIT = {
    "item_id": "a",
    "score": 0.9,
    "memory_type": "semantic",
    "origin": "chat",
    "title": "t",
    "snippet": "s",
    "created_at": "2026-10-21T00:00:00Z",
    "space": SPACE,
    "has_graph_node": True,
    "embedding_preview": PREVIEW,
}
# Deliberately unsorted and over-long: the SDK must hand the body back untouched.
QUERY_BODY = {
    "query": {"mode": "text", "dimension": 4, "space": SPACE},
    "hits": [dict(HIT, item_id="b", score=0.2), dict(HIT, score=0.9)],
    "truncated": True,
    "timing_ms": {"embed": None, "search": 1.5},
}
STATS_BODY = {
    "backend": "falkordb",
    "single_tenant": False,
    "capabilities": {
        "scope_pushdown": True,
        "scoped_exact": False,
        "missing_list": True,
    },
    "embedder": {"model_id": "m", "dimension": 4},
    "collections": [
        {"name": "memory", "count": 2, "space": SPACE, "missing_count": None}
    ],
    "scope": {"workspace_id": "ws", "user_id": None, "isolation": "WORKSPACE"},
    "warnings": [],
}
INSPECT_BODY = {
    "item": {"item_id": "a", "vector": {"present": True, "embedding_preview": PREVIEW}},
    "neighbours": [HIT],
    "space": SPACE,
}
PROJECTION_BODY = {
    "method": "pca",
    "dims": 3,
    "space": SPACE,
    "points": [
        {
            "item_id": "a",
            "coords": [0.1, -0.2, 0.3],
            "memory_type": "semantic",
            "title": None,
            "has_graph_node": True,
        }
    ],
    "total": 1,
    "sampled": False,
    "limit": 2000,
    "explained_variance": [0.6, 0.3, 0.1],
    "warnings": [],
    "cached": False,
}
MISSING_BODY = {
    "items": [{"item_id": "z", "reason": "no_row"}],
    "next_cursor": "opaque-2",
    "total": None,
}


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test_token")


def _ok(body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = body
    return resp


def _error(status: int, text: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text or f"error {status}"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status} Error", request=MagicMock(spec=httpx.Request), response=resp
    )
    return resp


# (id, call, method, path suffix, params, json body, response body).
# Every parameter of every route appears in at least one row; the *_clamp rows send
# values over the server maximum and expect them forwarded unchanged.
REQUEST_ROWS = [
    (
        "query_text_defaults",
        lambda c: c.vector_query(text="hello"),
        "POST",
        "/memory/vector/query",
        None,
        {
            "text": "hello",
            "top_k": 10,
            "collection": "memory",
            "include_embedding": False,
        },
        QUERY_BODY,
    ),
    (
        "query_embedding_all_filters",
        lambda c: c.vector_query(
            embedding=[0.1, 0.2],
            top_k=5,
            memory_type="semantic",
            origin_prefix="chat:",
            collection="structure",
            include_embedding=True,
        ),
        "POST",
        "/memory/vector/query",
        None,
        {
            "embedding": [0.1, 0.2],
            "top_k": 5,
            "memory_type": "semantic",
            "origin_prefix": "chat:",
            "collection": "structure",
            "include_embedding": True,
        },
        QUERY_BODY,
    ),
    (
        "query_top_k_clamp_not_reimplemented",
        lambda c: c.vector_query(text="x", top_k=500),
        "POST",
        "/memory/vector/query",
        None,
        {"text": "x", "top_k": 500, "collection": "memory", "include_embedding": False},
        QUERY_BODY,
    ),
    (
        "query_neither_forwarded_for_server_400",
        lambda c: c.vector_query(),
        "POST",
        "/memory/vector/query",
        None,
        {"top_k": 10, "collection": "memory", "include_embedding": False},
        QUERY_BODY,
    ),
    (
        "stats",
        lambda c: c.vector_stats(),
        "GET",
        "/memory/vector/stats",
        None,
        None,
        STATS_BODY,
    ),
    (
        "inspect_defaults",
        lambda c: c.vector_inspect("a"),
        "GET",
        "/memory/vector/items/a",
        {"top_k": 10, "collection": "memory", "include_embedding": False},
        None,
        INSPECT_BODY,
    ),
    (
        "inspect_all_params_and_quoted_id",
        lambda c: c.vector_inspect(
            "a/b c", top_k=3, collection="structure", include_embedding=True
        ),
        "GET",
        "/memory/vector/items/a%2Fb%20c",
        {"top_k": 3, "collection": "structure", "include_embedding": True},
        None,
        INSPECT_BODY,
    ),
    (
        "inspect_top_k_clamp_not_reimplemented",
        lambda c: c.vector_inspect("a", top_k=99),
        "GET",
        "/memory/vector/items/a",
        {"top_k": 99, "collection": "memory", "include_embedding": False},
        None,
        INSPECT_BODY,
    ),
    (
        "missing_first_page_no_cursor_key",
        lambda c: c.vector_missing(),
        "GET",
        "/memory/vector/missing",
        {"limit": 50, "collection": "memory"},
        None,
        MISSING_BODY,
    ),
    (
        "missing_cursor_collection_passed_verbatim",
        lambda c: c.vector_missing(limit=10, cursor="opaque-2", collection="structure"),
        "GET",
        "/memory/vector/missing",
        {"limit": 10, "cursor": "opaque-2", "collection": "structure"},
        None,
        MISSING_BODY,
    ),
    (
        "missing_limit_clamp_not_reimplemented",
        lambda c: c.vector_missing(limit=1000),
        "GET",
        "/memory/vector/missing",
        {"limit": 1000, "collection": "memory"},
        None,
        MISSING_BODY,
    ),
    (
        "projection_defaults_no_limit_key",
        lambda c: c.vector_projection(),
        "GET",
        "/memory/vector/projection",
        {"dims": 3, "method": "pca", "collection": "memory"},
        None,
        PROJECTION_BODY,
    ),
    (
        "projection_all_params_and_limit_clamp_not_reimplemented",
        lambda c: c.vector_projection(
            dims=2, method="umap", limit=5000, collection="structure"
        ),
        "GET",
        "/memory/vector/projection",
        {"dims": 2, "method": "umap", "limit": 5000, "collection": "structure"},
        None,
        PROJECTION_BODY,
    ),
]


@pytest.mark.parametrize(
    ("call", "method", "path", "params", "body", "response"),
    [row[1:] for row in REQUEST_ROWS],
    ids=[row[0] for row in REQUEST_ROWS],
)
@patch("httpx.Client.request")
def test_vector_request_shape_and_untouched_body(
    mock_request, client, call, method, path, params, body, response
):
    mock_request.return_value = _ok(response)

    result = call(client)

    assert result == response
    assert mock_request.call_args.args[0] == method
    assert mock_request.call_args.args[1] == f"http://localhost:9001{path}"
    assert "?" not in mock_request.call_args.args[1]
    assert mock_request.call_args.kwargs["params"] == params
    assert mock_request.call_args.kwargs["json"] == body


def test_vector_responses_keep_preview_only_nulls_and_cursor(client):
    """Preview stays 16 floats, null total and the cursor are returned as sent."""
    with patch("httpx.Client.request") as mock_request:
        mock_request.return_value = _ok(QUERY_BODY)
        hits = client.vector_query(text="x", include_embedding=True)["hits"]
        mock_request.return_value = _ok(MISSING_BODY)
        page = client.vector_missing()
    assert [h["item_id"] for h in hits] == ["b", "a"]
    assert all(len(h["embedding_preview"]) == 16 for h in hits)
    assert page["total"] is None and page["next_cursor"] == "opaque-2"


# Core returns null for these figures when the store's scope filters do not pin the
# caller (VEC-CONTRACT-NULLABLE-COUNTS-1). One row per figure: the body must come back
# with the null in place, not coerced to 0/False and not rejected.
NULL_FIGURE_ROWS = [
    (
        "query_truncated",
        lambda c: c.vector_query(text="x"),
        dict(QUERY_BODY, truncated=None),
        ("truncated",),
    ),
    (
        "stats_count",
        lambda c: c.vector_stats(),
        dict(STATS_BODY, collections=[dict(STATS_BODY["collections"][0], count=None)]),
        ("collections", 0, "count"),
    ),
    (
        "stats_missing_count",
        lambda c: c.vector_stats(),
        dict(
            STATS_BODY,
            collections=[dict(STATS_BODY["collections"][0], missing_count=None)],
        ),
        ("collections", 0, "missing_count"),
    ),
    (
        "missing_total",
        lambda c: c.vector_missing(),
        dict(MISSING_BODY, total=None),
        ("total",),
    ),
    (
        "projection_total",
        lambda c: c.vector_projection(),
        dict(PROJECTION_BODY, total=None),
        ("total",),
    ),
    (
        "projection_sampled",
        lambda c: c.vector_projection(),
        dict(PROJECTION_BODY, total=None, sampled=None),
        ("sampled",),
    ),
]


@pytest.mark.parametrize(
    ("call", "response", "path"),
    [row[1:] for row in NULL_FIGURE_ROWS],
    ids=[row[0] for row in NULL_FIGURE_ROWS],
)
@patch("httpx.Client.request")
def test_null_figures_round_trip_untouched(mock_request, client, call, response, path):
    mock_request.return_value = _ok(response)

    value = call(client)
    for key in path:
        value = value[key]

    assert value is None
    assert call(client) == response


# One row per (method, status) the contract lists, plus 500 (generic server error,
# which must NOT be typed as unsupported/substrate) for every method.
_QUERY = lambda c: c.vector_query(text="x")  # noqa: E731
_STATS = lambda c: c.vector_stats()  # noqa: E731
_INSPECT = lambda c: c.vector_inspect("a")  # noqa: E731
_MISSING = lambda c: c.vector_missing()  # noqa: E731
_PROJECTION = lambda c: c.vector_projection()  # noqa: E731

ERROR_ROWS = [
    ("query_400", _QUERY, 400, SmartMemoryValidationError),
    ("query_403", _QUERY, 403, SmartMemoryPermissionError),
    ("query_404", _QUERY, 404, SmartMemoryNotFoundError),
    ("query_501", _QUERY, 501, SmartMemoryUnsupportedError),
    ("query_503", _QUERY, 503, SmartMemorySubstrateError),
    ("query_500", _QUERY, 500, SmartMemoryServerError),
    ("stats_403", _STATS, 403, SmartMemoryPermissionError),
    ("stats_501", _STATS, 501, SmartMemoryUnsupportedError),
    ("stats_503", _STATS, 503, SmartMemorySubstrateError),
    ("stats_500", _STATS, 500, SmartMemoryServerError),
    ("inspect_403", _INSPECT, 403, SmartMemoryPermissionError),
    ("inspect_404", _INSPECT, 404, SmartMemoryNotFoundError),
    ("inspect_400", _INSPECT, 400, SmartMemoryValidationError),
    ("inspect_501", _INSPECT, 501, SmartMemoryUnsupportedError),
    ("inspect_503", _INSPECT, 503, SmartMemorySubstrateError),
    ("inspect_500", _INSPECT, 500, SmartMemoryServerError),
    ("missing_403", _MISSING, 403, SmartMemoryPermissionError),
    ("missing_404", _MISSING, 404, SmartMemoryNotFoundError),
    ("missing_400", _MISSING, 400, SmartMemoryValidationError),
    ("missing_501", _MISSING, 501, SmartMemoryUnsupportedError),
    ("missing_503", _MISSING, 503, SmartMemorySubstrateError),
    ("missing_500", _MISSING, 500, SmartMemoryServerError),
    ("projection_400", _PROJECTION, 400, SmartMemoryValidationError),
    ("projection_403", _PROJECTION, 403, SmartMemoryPermissionError),
    ("projection_404", _PROJECTION, 404, SmartMemoryNotFoundError),
    ("projection_501", _PROJECTION, 501, SmartMemoryUnsupportedError),
    ("projection_503", _PROJECTION, 503, SmartMemorySubstrateError),
    ("projection_500", _PROJECTION, 500, SmartMemoryServerError),
]


@pytest.mark.parametrize(
    ("call", "status", "exception"),
    [row[1:] for row in ERROR_ROWS],
    ids=[row[0] for row in ERROR_ROWS],
)
@patch("httpx.Client.request")
def test_vector_methods_raise_typed_errors(
    mock_request, client, call, status, exception
):
    mock_request.return_value = _error(status)

    with pytest.raises(exception) as exc:
        call(client)

    assert type(exc.value) is exception
    assert exc.value.status_code == status
    assert isinstance(exc.value, SmartMemoryClientError)


@pytest.mark.parametrize("status", [501, 503], ids=["501", "503"])
@patch("httpx.Client.request")
def test_unsupported_and_substrate_still_caught_as_server_error(
    mock_request, client, status
):
    mock_request.return_value = _error(status)
    with pytest.raises(SmartMemoryServerError):
        client.vector_stats()


@patch("httpx.Client.request")
def test_inspect_no_vector_detail_is_kept_on_the_404(mock_request, client):
    mock_request.return_value = _error(404, '{"detail": "no_vector"}')
    with pytest.raises(SmartMemoryNotFoundError) as exc:
        client.vector_inspect("a")
    assert "no_vector" in exc.value.detail
