"""SM-PATTERN-CRUD-1: adherence pattern client methods hit the pattern routes with the contract shapes."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)
from smartmemory_client.client import SmartMemoryClient

BASE = "http://localhost:9001"


@pytest.fixture
def client():
    return SmartMemoryClient(base_url=BASE, api_key="test-token")


def _ok(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _sent(mock_req):
    (method, url), kwargs = mock_req.call_args
    return method, url, kwargs.get("json"), kwargs.get("params")


@patch("httpx.Client.request")
def test_list_and_get(mock_req, client):
    mock_req.return_value = _ok({"patterns": [], "count": 0})
    client.list_patterns(severity="error", q="gather", limit=5)
    assert _sent(mock_req) == (
        "GET",
        f"{BASE}/memory/patterns",
        None,
        {"limit": 5, "severity": "error", "q": "gather"},
    )

    mock_req.return_value = _ok({"pattern": {"pattern_id": "pat_1"}})
    client.get_pattern("pat_1")
    assert _sent(mock_req)[:2] == ("GET", f"{BASE}/memory/patterns/pat_1")


@patch("httpx.Client.request")
def test_create_sends_every_field(mock_req, client):
    mock_req.return_value = _ok({"pattern": {}, "pattern_id": "pat_1"})
    out = client.create_pattern("T", "Rule", severity="error", scope=["**/*.py"])
    assert out["pattern_id"] == "pat_1"
    assert _sent(mock_req) == (
        "POST",
        f"{BASE}/memory/patterns",
        {
            "title": "T",
            "content": "Rule",
            "severity": "error",
            "scope": ["**/*.py"],
            "examples": [],
            "rationale": "",
            "source": "user",
        },
        None,
    )


@patch("httpx.Client.request")
def test_update_puts_only_given_fields_and_encodes_the_id(mock_req, client):
    mock_req.return_value = _ok({"pattern": {"version": 2}})
    client.update_pattern("pat/1", severity="warn", updated_by="sdk:me")
    assert _sent(mock_req) == (
        "PUT",
        f"{BASE}/memory/patterns/pat%2F1",
        {"severity": "warn", "updated_by": "sdk:me"},
        None,
    )


@patch("httpx.Client.request")
def test_retire_is_the_soft_delete_with_a_reason(mock_req, client):
    mock_req.return_value = _ok({"pattern_id": "pat_1", "status": "retracted"})
    assert client.retire_pattern("pat_1", reason="obsolete")["status"] == "retracted"
    assert _sent(mock_req) == (
        "DELETE",
        f"{BASE}/memory/patterns/pat_1",
        None,
        {"reason": "obsolete"},
    )


@patch("httpx.Client.request")
def test_seed_sends_text_never_a_path(mock_req, client):
    mock_req.return_value = _ok({"created": ["pat_1"], "skipped": []})
    client.seed_patterns("- [A](a.md) — a.", {"a.md": "body"})
    method, url, body, params = _sent(mock_req)
    assert (method, url, params) == ("POST", f"{BASE}/memory/patterns/seed", None)
    assert body == {
        "index_text": "- [A](a.md) — a.",
        "files": {"a.md": "body"},
        "refused": {},
        "source_prefix": "memory_md",
    }


@patch("httpx.Client.request")
def test_protected_field_422_surfaces_as_validation_error(mock_req, client):
    resp = MagicMock()
    resp.status_code = 422
    resp.text = "extra fields not permitted"
    resp.json.return_value = {"detail": "extra fields not permitted"}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "422", request=MagicMock(), response=resp
    )
    mock_req.return_value = resp
    with pytest.raises(SmartMemoryValidationError):
        client.update_pattern("pat_1", status="retracted")


CALLS = {
    "list_patterns": lambda c: c.list_patterns(),
    "get_pattern": lambda c: c.get_pattern("pat_x"),
    "create_pattern": lambda c: c.create_pattern("T", "Rule"),
    "update_pattern": lambda c: c.update_pattern("pat_x", severity="warn"),
    "retire_pattern": lambda c: c.retire_pattern("pat_x"),
    "seed_patterns": lambda c: c.seed_patterns("- [A](a.md) — a."),
}
ERRORS = [
    (403, SmartMemoryPermissionError),
    (404, SmartMemoryNotFoundError),
    (400, SmartMemoryValidationError),
    (500, SmartMemoryServerError),
]
ERROR_ROWS = [(name, status, exc) for name in CALLS for status, exc in ERRORS]


@pytest.mark.parametrize(
    "name,status,exc", ERROR_ROWS, ids=[f"{n}-{s}" for n, s, _ in ERROR_ROWS]
)
@patch("httpx.Client.request")
def test_errors_raise_typed(mock_req, client, name, status, exc):
    resp = MagicMock()
    resp.status_code = status
    resp.text = "error"
    resp.json.return_value = {"detail": "error"}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=resp
    )
    mock_req.return_value = resp
    with pytest.raises(exc) as exc_info:
        CALLS[name](client)
    assert exc_info.value.status_code == status
