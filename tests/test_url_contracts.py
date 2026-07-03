"""URL contract tests for public SmartMemoryClient API methods.

Path fixes in this change: none. The covered client methods already match the
service routes under ../smart-memory-service/memory_service/api/routes/.
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient

BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc123"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _ok(json_data: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.text = ""
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data or {
        "id": "item_123",
        "item_id": "item_123",
        "content": "contract response",
        "memory_type": "semantic",
        "metadata": {},
        "results": [],
        "decisions": [],
        "neighbors": [],
    }
    return resp


def _called_method(mock_request: MagicMock) -> str:
    return mock_request.call_args.args[0]


def _called_path(mock_request: MagicMock) -> str:
    url = mock_request.call_args.args[1]
    assert url.startswith(BASE_URL)
    return url.removeprefix(BASE_URL)


@pytest.mark.parametrize(
    ("method_name", "args", "expected_verb", "expected_path"),
    [
        # Memory CRUD/search/context/link surfaces.
        ("add", ("remember this",), "POST", "/memory/add"),
        ("get", ("item_123",), "GET", "/memory/item_123"),
        ("update", ("item_123", "updated content"), "PATCH", "/memory/item_123"),
        ("delete", ("item_123",), "DELETE", "/memory/item_123"),
        ("search", ("python sdk",), "POST", "/memory/search"),
        ("search_advanced", ("python sdk",), "POST", "/memory/search/advanced"),
        ("search_by_metadata", ("source", "docs"), "GET", "/memory/by-metadata"),
        (
            "get_working_context",
            ("session_123", "what matters?"),
            "POST",
            "/memory/context",
        ),
        ("summary", (), "GET", "/memory/summary"),
        ("link", ("item_123", "item_456"), "POST", "/memory/link"),
        ("add_edge", ("item_123", "item_456", "RELATED"), "POST", "/memory/edge"),
        ("get_neighbors", ("item_123",), "GET", "/memory/item_123/neighbors"),
        ("get_links", ("item_123",), "GET", "/memory/item_123/links"),
        ("get_lineage", ("item_123",), "GET", "/memory/item_123/lineage"),
        # Ingest/enrichment surfaces.
        ("ingest", ("content to ingest",), "POST", "/memory/ingest"),
        ("ingest_full", ("content to ingest",), "POST", "/memory/ingest/full"),
        (
            "ingest_conversation",
            ([{"role": "user", "content": "hello"}],),
            "POST",
            "/memory/ingest/conversation",
        ),
        ("enrich", ("item_123",), "POST", "/memory/item_123/enrich"),
        (
            "personalize",
            ({"style": "direct"}, {"language": "en"}),
            "POST",
            "/memory/personalize",
        ),
        (
            "ground",
            ("item_123", "https://example.com/source"),
            "POST",
            "/memory/item_123/ground",
        ),
        # Code surfaces.
        ("code_search", ("auth",), "GET", "/memory/code/search"),
        ("code_index", ("/repo/src",), "POST", "/memory/code/index"),
        ("code_context", ("SmartMemoryClient",), "GET", "/memory/code/context"),
        ("code_dead_code", ("smartmemory",), "GET", "/memory/code/dead-code"),
        (
            "code_dependencies",
            ("SmartMemoryClient",),
            "GET",
            "/memory/code/dependencies",
        ),
        # Plan surfaces.
        ("get_plan", ("plan_abcdef123456",), "GET", "/memory/plans/plan_abcdef123456"),
        (
            "update_plan_task",
            ("plan_abcdef123456", "task_1", "complete"),
            "PATCH",
            "/memory/plans/plan_abcdef123456/task",
        ),
        (
            "complete_plan",
            ("plan_abcdef123456",),
            "POST",
            "/memory/plans/plan_abcdef123456/complete",
        ),
        (
            "fail_plan",
            ("plan_abcdef123456", "blocked"),
            "POST",
            "/memory/plans/plan_abcdef123456/fail",
        ),
        # Decision surfaces.
        (
            "create_decision",
            ("Use contract tests",),
            "POST",
            "/memory/decisions/create",
        ),
        ("get_decision", ("decision_123",), "GET", "/memory/decisions/decision_123"),
        ("list_decisions", (), "GET", "/memory/decisions"),
        (
            "supersede_decision",
            ("decision_123", "Use route contract tests", "more precise"),
            "POST",
            "/memory/decisions/decision_123/supersede",
        ),
        (
            "retract_decision",
            ("decision_123", "obsolete"),
            "POST",
            "/memory/decisions/decision_123/retract",
        ),
        (
            "reinforce_decision",
            ("decision_123", "item_123"),
            "POST",
            "/memory/decisions/decision_123/reinforce",
        ),
        (
            "get_provenance_chain",
            ("decision_123",),
            "GET",
            "/memory/decisions/decision_123/provenance",
        ),
        (
            "get_causal_chain",
            ("decision_123",),
            "GET",
            "/memory/decisions/decision_123/causal-chain",
        ),
        (
            "create_pending_decision",
            ("Ship it", [{"description": "tests pass"}]),
            "POST",
            "/memory/decisions/pending/create",
        ),
        (
            "resolve_requirement",
            ("decision_123", "req_1", "item_123"),
            "POST",
            "/memory/decisions/pending/decision_123/resolve",
        ),
        (
            "try_activate_decision",
            ("decision_123",),
            "POST",
            "/memory/decisions/pending/decision_123/activate",
        ),
        ("list_pending_decisions", (), "GET", "/memory/decisions/pending"),
        # Reasoning trace surfaces.
        (
            "extract_reasoning",
            ("Thought: test. Conclusion: pass.",),
            "POST",
            "/memory/reasoning/traces/extract",
        ),
        (
            "store_reasoning_trace",
            ({"trace_id": "trace_123", "steps": []},),
            "POST",
            "/memory/reasoning/traces/store",
        ),
        ("query_reasoning", ("why tests?",), "POST", "/memory/reasoning/traces/query"),
        (
            "get_reasoning_trace",
            ("trace_123",),
            "GET",
            "/memory/reasoning/traces/trace_123",
        ),
        # Summary snapshot surfaces.
        ("summary_generate", (), "POST", "/memory/summary/generate"),
        ("summary_latest", (), "GET", "/memory/summary/latest"),
        ("summary_get", ("snapshot_123",), "GET", "/memory/summary/snapshot_123"),
        ("summary_list", (), "GET", "/memory/summary/list"),
        ("summary_delta", ("snapshot_1", "snapshot_2"), "GET", "/memory/summary/delta"),
        ("summary_delete", ("snapshot_123",), "DELETE", "/memory/summary/snapshot_123"),
    ],
)
@patch("httpx.Client.request")
def test_public_api_method_urls(
    mock_request: MagicMock,
    client: SmartMemoryClient,
    method_name: str,
    args: tuple,
    expected_verb: str,
    expected_path: str,
) -> None:
    mock_request.return_value = _ok()

    getattr(client, method_name)(*args)

    assert _called_method(mock_request) == expected_verb
    assert _called_path(mock_request) == expected_path
