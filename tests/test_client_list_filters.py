"""SVC-LIST-EXCLUDE-ENTITY-1 part B: `list_memories(exclude_node_category=, q=)`.

Mocked at the HTTP boundary (`httpx.Client.request`). The wire query string is built with
`httpx.QueryParams`, the encoder httpx applies to the `params` dict, so a repeated param is
asserted as it would be sent. Contract: GRAPH-API-1l/list-filters-contract.json 1.1.0.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient

BASE = "limit=50&offset=0&order=asc"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url="http://localhost:9001", api_key="test_token_abc123"
    )


def _ok(json_data: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.text = ""
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data or {"items": [], "total": 0}
    return resp


# One row per input shape: (case, kwargs, exact query string).
ROWS = [
    ("omitted", {}, BASE),
    ("none", {"exclude_node_category": None, "q": None}, BASE),
    ("empty list sends nothing", {"exclude_node_category": []}, BASE),
    (
        "one category",
        {"exclude_node_category": ["entity"]},
        f"{BASE}&exclude_node_category=entity",
    ),
    (
        "bare string is one value",
        {"exclude_node_category": "entity"},
        f"{BASE}&exclude_node_category=entity",
    ),
    (
        "tuple of several repeats the param in order",
        {"exclude_node_category": ("entity", "grounding")},
        f"{BASE}&exclude_node_category=entity&exclude_node_category=grounding",
    ),
    ("q only", {"q": "robot arm"}, f"{BASE}&q=robot+arm"),
    ("q with reserved characters", {"q": "a&b=c#d"}, f"{BASE}&q=a%26b%3Dc%23d"),
    (
        "both, with type, metadata and grounding",
        {
            "memory_type": "semantic",
            "metadata_key": "topic",
            "metadata_value": "x",
            "include_grounding": False,
            "exclude_node_category": ["entity"],
            "q": "arm",
        },
        f"{BASE}&metadata_key=topic&metadata_value=x&memory_type=semantic"
        "&include_grounding=false&exclude_node_category=entity&q=arm",
    ),
]


@pytest.mark.parametrize(
    "kwargs,expected", [(r[1], r[2]) for r in ROWS], ids=[r[0] for r in ROWS]
)
@patch("httpx.Client.request")
def test_list_memories_wire_query(mock_request, client, kwargs, expected) -> None:
    mock_request.return_value = _ok()

    client.list_memories(**kwargs)

    assert mock_request.call_args.args[0] == "GET"
    assert mock_request.call_args.args[1].endswith("/memory/list")
    assert str(httpx.QueryParams(mock_request.call_args.kwargs["params"])) == expected


@patch("httpx.Client.request")
def test_over_limit_input_is_sent_untouched_so_the_service_rejects_it(
    mock_request, client
) -> None:
    """21 categories and a 201-character q are the service's 422, never a silent truncation here."""
    mock_request.return_value = _ok()
    categories = [f"c{i}" for i in range(21)]

    client.list_memories(exclude_node_category=categories, q="x" * 201)

    params = mock_request.call_args.kwargs["params"]
    assert params["exclude_node_category"] == categories
    assert params["q"] == "x" * 201


@patch("httpx.Client.request")
def test_filtered_envelope_is_returned_unchanged(mock_request, client) -> None:
    page = {
        "items": [{"item_id": "m1"}],
        "total": 7,
        "limit": 50,
        "offset": 0,
        "policy": {"include_grounding": False, "source": "env"},
    }
    mock_request.return_value = _ok(page)

    assert client.list_memories(exclude_node_category=["entity"]) == page
