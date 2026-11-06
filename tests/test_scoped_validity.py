"""U09 wire serialization and status/detail preservation, separate from golden HTTP."""

import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryClient,
    SmartMemoryValidationError,
    SmartMemoryPermissionError,
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
)

SCOPED_VALIDITY_VERSION = 2
CONTRACT_DIGEST = "26c6580effb9ac8e11e5471ef35489f66319f5419cc15d9f7e97781d0f5ba4eb"
FIXTURES_DIGEST = "a4756030405465024f25ba7ba1665b4fd8e1e3cf2972b63ae6e1c8107561aa07"


def test_u01_canonical_pins():
    workspace = next(
        p for p in Path(__file__).resolve().parents if (p / "WORKSPACE.md").is_file()
    )
    directory = (
        workspace
        / ".worktrees/scoped-validity-docs-2.0/docs/features/SM-SCOPED-VALIDITY-1"
    )
    for filename, expected in [
        ("scoped-validity-contract.json", CONTRACT_DIGEST),
        ("scoped-validity-fixtures.json", FIXTURES_DIGEST),
    ]:
        card = json.loads((directory / filename).read_text())
        assert card["version"] == SCOPED_VALIDITY_VERSION
        assert (
            hashlib.sha256(
                json.dumps(
                    card, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
            == expected
        )


AT = datetime(2026, 2, 1, 8, tzinfo=timezone(timedelta(hours=8)))
UTC = "2026-02-01T00:00:00+00:00"
READS = [
    ("get_decision", ("old",)),
    ("list_decisions", ()),
    ("search_decisions", ("CRF",)),
    ("get_provenance_chain", ("old",)),
]
WRITES = [
    ("create_decision", ("CRF",), {}),
    ("supersede_decision", ("old", "new", "reason"), {}),
    (
        "supersede",
        ("old",),
        {"content": "new", "memory_type": "semantic", "reason": "reason"},
    ),
    ("supersede_link", ("old", "new", "reason"), {}),
]


@pytest.fixture
def wire():
    calls = []
    with SmartMemoryClient(
        base_url="https://sdk-test.invalid", api_key="synthetic"
    ) as client:
        client._client.close()

        def answer(request):
            calls.append(request)
            return httpx.Response(200, json={"decisions": [], "results": []})

        client._client = httpx.Client(transport=httpx.MockTransport(answer))
        yield client, calls


@pytest.mark.parametrize("method,args", READS)
def test_get_encoding_utc_and_asof(wire, method, args):
    client, calls = wire
    scope = {"site": "A & B/中文"}
    getattr(client, method)(
        *args, business_scope=scope, valid_at=AT, as_of="2026-03-01T00:00:00Z"
    )
    params = calls[-1].url.params
    assert json.loads(params["business_scope"]) == scope
    assert params["valid_at"] == UTC
    assert params["as_of"] == "2026-03-01T00:00:00Z"


@pytest.mark.parametrize("method,args,kwargs", WRITES)
def test_schedule_conversion_without_mutation(wire, method, args, kwargs):
    client, calls = wire
    schedule = [{"scope": {"site": "A"}, "valid_from": AT}]
    getattr(client, method)(*args, **kwargs, scope_go_lives=schedule)
    assert json.loads(calls[-1].content)["scope_go_lives"] == [
        {"scope": {"site": "A"}, "valid_from": UTC}
    ]
    assert schedule[0]["valid_from"] is AT


@pytest.mark.parametrize("method,args,kwargs", WRITES[1:])
def test_scalar_date(wire, method, args, kwargs):
    client, calls = wire
    getattr(client, method)(*args, **kwargs, valid_from=AT)
    assert json.loads(calls[-1].content)["valid_from"] == UTC


@pytest.mark.parametrize("method,args,kwargs", [(m, a, {}) for m, a in READS] + WRITES)
def test_absent_options_compatible(wire, method, args, kwargs):
    client, calls = wire
    getattr(client, method)(*args, **kwargs)
    payload = (
        dict(calls[-1].url.params)
        if calls[-1].method == "GET"
        else json.loads(calls[-1].content)
    )
    assert not (
        {"business_scope", "valid_at", "scope_go_lives", "valid_from"} & payload.keys()
    )


def test_search_qualifiers(wire):
    client, calls = wire
    client.search("CRF", business_scope={"site": "B"}, valid_at=AT, as_of_date=AT)
    body = json.loads(calls[-1].content)
    assert body["business_scope"] == {"site": "B"}
    assert body["valid_at"] == UTC
    assert body["as_of_date"] == AT.isoformat()


@pytest.mark.parametrize(
    "status,exception",
    [
        (400, SmartMemoryValidationError),
        (409, SmartMemoryValidationError),
        (401, SmartMemoryPermissionError),
        (403, SmartMemoryPermissionError),
        (404, SmartMemoryNotFoundError),
        (500, SmartMemoryServerError),
        (503, SmartMemoryServerError),
    ],
)
def test_typed_errors_all_surfaces_no_retry(status, exception):
    calls = []
    detail = {
        "code": "scoped_validity_conflict"
        if status == 409
        else "invalid_scoped_validity",
        "message": "retained",
    }

    def answer(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": detail})

    with SmartMemoryClient(
        base_url="https://sdk-test.invalid", api_key="synthetic"
    ) as client:
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(answer))
        for method, args, kwargs in (
            [(m, a, {}) for m, a in READS] + WRITES + [("search", ("CRF",), {})]
        ):
            before = len(calls)
            opts = (
                {"scope_go_lives": []}
                if method in {m for m, _, _ in WRITES}
                else {"business_scope": {"site": "A"}}
            )
            with pytest.raises(exception) as error:
                getattr(client, method)(*args, **kwargs, **opts)
            assert error.value.status_code == status
            assert json.loads(error.value.detail)["detail"] == detail
            assert len(calls) == before + 1


@pytest.mark.parametrize(
    "value,expected",
    [(datetime(2026, 2, 1), UTC), ("2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z")],
)
def test_naive_datetime_utc_and_string_passthrough(wire, value, expected):
    client, calls = wire
    client.get_decision("old", valid_at=value)
    assert calls[-1].url.params["valid_at"] == expected
