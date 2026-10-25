"""Prepared explicit public waits (U49.A2, C-49.contract.sdk-suites; G11, G12, G47).

The helper in ``tests/public_wait.py`` is prepared, not yet used by a converted test: the client's save-then-read
tests are real-service integration tests owned by the ring-3 SDK harness (``tests/data/save_then_read_census.json``).
These rows prove the prepared calls surface every outcome the unit requires: queued past the deadline, a fault that
stays visible with no retry, the reached milestone, and a legacy direct read that is unchanged.
"""

import ast
import dataclasses
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

import smartmemory_client
from smartmemory_client import (
    MemoryItem,
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
)
from smartmemory_client.errors import SmartMemoryTransportError
from tests.public_wait import (
    OUTCOMES,
    Observation,
    PublicWaitArgumentError,
    PublicWaitRefused,
    PublicWaitStatusUnobservable,
    await_public,
    observe_get,
    observe_search,
    refuse,
)

# --- SHARED BEGIN (byte-identical in smart-memory-client and smart-memory-mcp tests/test_public_wait.py) ---
WARN_PREFIX = "Explicit public wait refused: "
PENDING = Observation(detail="pending")
STORED = Observation(stage="stored", detail="stored")
FAILED = Observation(stage="stored", terminal=True, outcome="failed")


def done(stage, outcome):
    return Observation(stage=stage, terminal=True, outcome=outcome)


class Clock:
    """A fake clock whose sleep advances it. Binary-exact steps keep every elapsed value exact."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Script:
    """An observer that replays ``steps`` (the last one repeats) and counts its reads."""

    def __init__(self, steps):
        self.steps, self.reads = list(steps), 0

    def __call__(self):
        step = self.steps[min(self.reads, len(self.steps) - 1)]
        self.reads += 1
        if isinstance(step, BaseException):
            raise step
        return step


def warnings(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "public_wait" and r.levelno >= logging.WARNING
    ]


def drive(observe, **kwargs):
    clock = Clock()
    kwargs = {"poll_s": 0.125, **kwargs}
    return await_public(observe, clock=clock.clock, sleep=clock.sleep, **kwargs), clock


HELD = Observation(stage="stored", held="paused")
SPAN = [0.125, 0.25, 0.5, 0.125]

# id, wait, deadline_s, steps, outcome, attempts, sleeps, warnings
CORE_ROWS = [
    ("stored on the first read", "stored", 1.0, [STORED], "reached", 1, [], []),
    (
        "queued then stored",
        "stored",
        1.0,
        [PENDING, PENDING, STORED],
        "reached",
        3,
        [0.125, 0.25],
        [],
    ),
    (
        "queued past the deadline",
        "stored",
        1.0,
        [PENDING],
        "client_timed_out",
        5,
        SPAN,
        [],
    ),
    (
        "deadline 0 reads once and times out",
        "stored",
        0,
        [PENDING, STORED],
        "client_timed_out",
        1,
        [],
        [],
    ),
    ("deadline 0 reached on the one read", "stored", 0, [STORED], "reached", 1, [], []),
    (
        "failed on the first read is not retried",
        "stored",
        1.0,
        [FAILED, STORED],
        "failed",
        1,
        [],
        [],
    ),
    (
        "failed after pending is returned when it appears",
        "stored",
        1.0,
        [PENDING, FAILED, STORED],
        "failed",
        2,
        [0.125],
        [],
    ),
    (
        "dead stays dead",
        "extracted",
        1.0,
        [done("stored", "dead"), STORED],
        "dead",
        1,
        [],
        [],
    ),
    (
        "skipped stays skipped",
        "extracted",
        1.0,
        [done("extracted", "skipped"), STORED],
        "skipped",
        1,
        [],
        [],
    ),
    (
        "partial stays partial",
        "terminal",
        1.0,
        [done("extracted", "partial"), STORED],
        "partial",
        1,
        [],
        [],
    ),
    (
        "completed at stored does not reach extracted",
        "extracted",
        1.0,
        [done("stored", "completed")],
        "unreached",
        1,
        [],
        [],
    ),
    (
        "completed no_op reaches terminal",
        "terminal",
        1.0,
        [done("stored", "no_op")],
        "reached",
        1,
        [],
        [],
    ),
    (
        "completed at extracted reaches extracted",
        "extracted",
        1.0,
        [done("extracted", "completed")],
        "reached",
        1,
        [],
        [],
    ),
    (
        "stored only, extracted wanted, times out",
        "extracted",
        1.0,
        [STORED],
        "client_timed_out",
        5,
        SPAN,
        [],
    ),
    (
        "still running, terminal wanted, times out",
        "terminal",
        1.0,
        [Observation(stage="extracted")],
        "client_timed_out",
        5,
        SPAN,
        [],
    ),
    (
        "a held run is refused once and not polled",
        "stored",
        1.0,
        [HELD, STORED],
        "refused",
        1,
        [],
        [
            "Explicit public wait: the run is held ('paused'); reported refused, not polled further"
        ],
    ),
]


@pytest.mark.parametrize("row", CORE_ROWS, ids=[r[0] for r in CORE_ROWS])
def test_each_scripted_read_sequence_has_its_outcome(row, caplog):
    _, wait, deadline_s, steps, outcome, attempts, sleeps, warned = row
    observe = Script(steps)
    result, clock = drive(observe, wait=wait, deadline_s=deadline_s)
    assert (result.outcome, result.attempts, observe.reads) == (
        outcome,
        attempts,
        attempts,
    )
    assert result.outcome in OUTCOMES and result.wait == wait
    assert (clock.sleeps, result.elapsed_s) == (sleeps, clock.now)
    assert result.last is observe.steps[min(attempts - 1, len(steps) - 1)]
    assert warnings(caplog) == warned


class Unprintable(Exception):
    def __str__(self):
        raise RuntimeError("no text")


# id, wait, steps, message
REFUSAL_ROWS = [
    (
        "the read raises",
        "stored",
        [RuntimeError("boom"), STORED],
        "the read through the public seam failed (RuntimeError: boom)",
    ),
    (
        "the error message cannot be formatted",
        "stored",
        [Unprintable(), STORED],
        "the read through the public seam failed (Unprintable: <unprintable>)",
    ),
    (
        "the read is not an Observation",
        "stored",
        ["stored"],
        "the read returned str, not an Observation",
    ),
    (
        "an unknown terminal outcome",
        "stored",
        [done("stored", "weird")],
        "a terminal observation carries outcome 'weird'",
    ),
    (
        "a terminal observation with no outcome",
        "stored",
        [done("stored", None)],
        "a terminal observation carries outcome None",
    ),
    (
        "extracted wanted from a seam with no status",
        "extracted",
        [Observation(stage="stored", status_carried=False, detail="d")],
        "this public seam carries no extraction or terminal status, so wait='extracted' is unobservable (only 'stored' is); last read: d",
    ),
    (
        "terminal wanted from a seam with no status",
        "terminal",
        [Observation(status_carried=False)],
        "this public seam carries no extraction or terminal status, so wait='terminal' is unobservable (only 'stored' is); last read: none",
    ),
]


@pytest.mark.parametrize("row", REFUSAL_ROWS, ids=[r[0] for r in REFUSAL_ROWS])
def test_an_unanswerable_read_is_one_typed_refusal_and_never_retried(row, caplog):
    _, wait, steps, message = row
    observe = Script(steps)
    with pytest.raises(PublicWaitRefused) as caught:
        drive(observe, wait=wait, deadline_s=1.0)
    assert type(caught.value) is PublicWaitRefused and str(caught.value) == message
    assert observe.reads == 1
    assert warnings(caplog) == [WARN_PREFIX + message]


def test_a_refusal_an_adapter_raised_is_logged_once_not_twice(caplog):
    observe = Script([refuse("seam said no")])
    with pytest.raises(PublicWaitRefused, match="seam said no"):
        drive(observe, wait="stored", deadline_s=1.0)
    assert observe.reads == 1 and warnings(caplog) == [WARN_PREFIX + "seam said no"]


BAD_WAIT = "wait must be one of ('stored', 'extracted', 'terminal'), got "
# id, kwargs, message
ARGUMENT_ROWS = [
    ("wait None", {"wait": None, "deadline_s": 1.0}, BAD_WAIT + "None"),
    ("wait unknown", {"wait": "bogus", "deadline_s": 1.0}, BAD_WAIT + "'bogus'"),
    ("wait a number", {"wait": 1, "deadline_s": 1.0}, BAD_WAIT + "1"),
    (
        "deadline negative",
        {"wait": "stored", "deadline_s": -1},
        "deadline_s must be a finite number >= 0, got -1",
    ),
    (
        "deadline nan",
        {"wait": "stored", "deadline_s": float("nan")},
        "deadline_s must be a finite number >= 0, got nan",
    ),
    (
        "deadline inf",
        {"wait": "stored", "deadline_s": float("inf")},
        "deadline_s must be a finite number >= 0, got inf",
    ),
    (
        "deadline a bool",
        {"wait": "stored", "deadline_s": True},
        "deadline_s must be a finite number >= 0, got True",
    ),
    (
        "deadline a string",
        {"wait": "stored", "deadline_s": "1"},
        "deadline_s must be a finite number >= 0, got '1'",
    ),
    (
        "deadline None",
        {"wait": "stored", "deadline_s": None},
        "deadline_s must be a finite number >= 0, got None",
    ),
    (
        "poll zero",
        {"wait": "stored", "deadline_s": 1.0, "poll_s": 0},
        "poll_s must be a positive finite number, got 0",
    ),
    (
        "poll negative",
        {"wait": "stored", "deadline_s": 1.0, "poll_s": -1},
        "poll_s must be a positive finite number, got -1",
    ),
    (
        "poll nan",
        {"wait": "stored", "deadline_s": 1.0, "poll_s": float("nan")},
        "poll_s must be a positive finite number, got nan",
    ),
    (
        "poll a bool",
        {"wait": "stored", "deadline_s": 1.0, "poll_s": True},
        "poll_s must be a positive finite number, got True",
    ),
    (
        "deadline too large for a float",
        {"wait": "stored", "deadline_s": 10**400},
        "deadline_s must be a finite number >= 0, got " + repr(10**400)[:48],
    ),
    (
        "deadline whose text cannot be formed",
        {"wait": "stored", "deadline_s": 10**5000},
        "deadline_s must be a finite number >= 0, got <unprintable>",
    ),
    (
        "first bad argument wins",
        {"wait": "bogus", "deadline_s": -1},
        BAD_WAIT + "'bogus'",
    ),
]


@pytest.mark.parametrize("row", ARGUMENT_ROWS, ids=[r[0] for r in ARGUMENT_ROWS])
def test_a_bad_argument_is_refused_before_any_read(row, caplog):
    _, kwargs, message = row
    observe = Script([STORED])
    with pytest.raises(PublicWaitArgumentError) as caught:
        drive(observe, **kwargs)
    assert str(caught.value) == message and isinstance(caught.value, ValueError)
    assert observe.reads == 0
    assert warnings(caplog) == [WARN_PREFIX + message]


@pytest.mark.parametrize(
    "observe, shown", [("x", "'x'"), (None, "None")], ids=["a string", "None"]
)
def test_an_observer_that_is_not_callable_is_refused(observe, shown, caplog):
    with pytest.raises(PublicWaitArgumentError):
        await_public(observe, wait="stored", deadline_s=1.0)
    assert warnings(caplog) == [WARN_PREFIX + f"observe must be callable, got {shown}"]


def test_the_helper_does_not_import_the_core_wait_module():
    tree = ast.parse((Path(__file__).parent / "public_wait.py").read_text())
    names = [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert [
        n
        for n in names
        if n == "smartmemory.testing" or n.startswith("smartmemory.testing.")
    ] == []


# --- SHARED END ---


BASE_URL = "http://localhost:9001"
ITEM = {"item_id": "m-1", "content": "hello", "memory_type": "semantic"}


def reply(status, json_data=None, text=""):
    response = MagicMock(spec=httpx.Response)
    response.status_code, response.text, response.headers = status, text, {}
    response.json.return_value = {} if json_data is None else json_data
    if status >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status} Error", request=MagicMock(spec=httpx.Request), response=response
        )
    return response


class Transport:
    """Replays HTTP replies at ``httpx.Client.request`` (the last one repeats) and counts the calls."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def __call__(self, *args, **kwargs):
        step = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(step, BaseException):
            raise step
        return step


def sdk(replies):
    transport = Transport(replies)
    client = SmartMemoryClient(base_url=BASE_URL, api_key="test_token_abc123")
    return client, transport


def listing(*ids):
    return reply(
        200, {"results": [{**ITEM, "item_id": i} for i in ids], "group_roots": []}
    )


NOT_FOUND, FOUND = reply(404, text="no such item"), reply(200, ITEM)
UNOBSERVABLE = (
    "{} returned a row but the SDK drops its read_status, so stored cannot be told from failed "
    "(status_unobservable, owner C49-SDK-STATUS-1)"
)
CARRY = "this public seam carries no extraction or terminal status, so wait={!r} is unobservable (only 'stored' is); last read: "

# id, replies, wait, deadline_s, outcome, attempts, calls, detail
GET_ROWS = [
    (
        "404 past the deadline is a visible timeout",
        [NOT_FOUND],
        "stored",
        1.0,
        "client_timed_out",
        5,
        5,
        "get('m-1') answered 404, not readable yet",
    ),
    (
        "deadline 0 reads once",
        [NOT_FOUND, FOUND],
        "stored",
        0,
        "client_timed_out",
        1,
        1,
        "get('m-1') answered 404, not readable yet",
    ),
]


@pytest.mark.parametrize("row", GET_ROWS, ids=[r[0] for r in GET_ROWS])
def test_get_family_outcomes(row, caplog):
    _, replies, wait, deadline_s, outcome, attempts, calls, detail = row
    client, transport = sdk(replies)
    with patch("httpx.Client.request", new=transport):
        result, _ = drive(observe_get(client, "m-1"), wait=wait, deadline_s=deadline_s)
    assert (result.outcome, result.attempts, transport.calls) == (
        outcome,
        attempts,
        calls,
    )
    assert result.last.detail == detail and warnings(caplog) == []


# id, replies, wait, calls, message
GET_REFUSAL_ROWS = [
    (
        "a 5xx is refused, never read as absence",
        [reply(500, text="boom"), FOUND],
        "stored",
        1,
        "get('m-1') failed (SmartMemoryServerError: Request failed: 500 Error - Detail: boom)",
    ),
    (
        "a 403 is refused",
        [reply(403, text="forbidden"), FOUND],
        "stored",
        1,
        "get('m-1') failed (SmartMemoryPermissionError: Request failed: 403 Error - Detail: forbidden)",
    ),
    (
        "a 400 is refused",
        [reply(400, text="bad id"), FOUND],
        "stored",
        1,
        "get('m-1') failed (SmartMemoryValidationError: Request failed: 400 Error - Detail: bad id)",
    ),
    (
        "a transport failure is refused",
        [httpx.ConnectError("refused"), FOUND],
        "stored",
        1,
        "get('m-1') failed (SmartMemoryTransportError: Request failed: refused)",
    ),
    (
        "a readable item is unobservable: the SDK dropped its status",
        [FOUND],
        "stored",
        1,
        UNOBSERVABLE.format("get('m-1')"),
    ),
    (
        "404 twice then readable is refused at the readable read, not reported stored",
        [NOT_FOUND, NOT_FOUND, FOUND],
        "stored",
        3,
        UNOBSERVABLE.format("get('m-1')"),
    ),
    (
        "extracted is refused for the same reason on a readable item",
        [FOUND],
        "extracted",
        1,
        UNOBSERVABLE.format("get('m-1')"),
    ),
    (
        "extracted is unobservable on a 404",
        [NOT_FOUND],
        "extracted",
        1,
        CARRY.format("extracted") + "get('m-1') answered 404, not readable yet",
    ),
    (
        "terminal is unobservable on a 404 too",
        [NOT_FOUND],
        "terminal",
        1,
        CARRY.format("terminal") + "get('m-1') answered 404, not readable yet",
    ),
]


@pytest.mark.parametrize("row", GET_REFUSAL_ROWS, ids=[r[0] for r in GET_REFUSAL_ROWS])
def test_get_family_refusals_are_typed_logged_once_and_never_retried(row, caplog):
    _, replies, wait, calls, message = row
    client, transport = sdk(replies)
    with patch("httpx.Client.request", new=transport), pytest.raises(PublicWaitRefused):
        drive(observe_get(client, "m-1"), wait=wait, deadline_s=1.0)
    assert transport.calls == calls and warnings(caplog) == [WARN_PREFIX + message]


def test_the_transport_refusal_names_a_subclass_of_the_base_client_error():
    """Row 'a transport failure is refused' logs the subclass name; callers catching the base class still catch it."""
    assert issubclass(SmartMemoryTransportError, SmartMemoryClientError)
    assert SmartMemoryTransportError is not SmartMemoryClientError


# id, replies, wait, deadline_s, outcome, attempts, calls, detail
SEARCH_ROWS = [
    (
        "never listed past the deadline is a visible timeout",
        [listing("m-0")],
        "stored",
        1.0,
        "client_timed_out",
        5,
        5,
        "search('q') did not list 'm-1' (1 rows)",
    ),
    (
        "deadline 0 reads once",
        [listing(), listing("m-1")],
        "stored",
        0,
        "client_timed_out",
        1,
        1,
        "search('q') did not list 'm-1' (0 rows)",
    ),
]


@pytest.mark.parametrize("row", SEARCH_ROWS, ids=[r[0] for r in SEARCH_ROWS])
def test_search_family_outcomes(row, caplog):
    _, replies, wait, deadline_s, outcome, attempts, calls, detail = row
    client, transport = sdk(replies)
    with patch("httpx.Client.request", new=transport):
        result, _ = drive(
            observe_search(client, "q", "m-1"), wait=wait, deadline_s=deadline_s
        )
    assert (result.outcome, result.attempts, transport.calls) == (
        outcome,
        attempts,
        calls,
    )
    assert result.last.detail == detail and warnings(caplog) == []


# id, replies, calls
SEARCH_REFUSAL_ROWS = [
    ("listed on the first search", [listing("m-1")], 1),
    (
        "empty twice then listed is refused at the listed read, not reported stored",
        [listing(), listing("m-0"), listing("m-0", "m-1")],
        3,
    ),
]


@pytest.mark.parametrize(
    "row", SEARCH_REFUSAL_ROWS, ids=[r[0] for r in SEARCH_REFUSAL_ROWS]
)
def test_a_listed_row_is_unobservable_because_the_sdk_dropped_its_status(row, caplog):
    _, replies, calls = row
    client, transport = sdk(replies)
    with (
        patch("httpx.Client.request", new=transport),
        pytest.raises(PublicWaitStatusUnobservable),
    ):
        drive(observe_search(client, "q", "m-1"), wait="stored", deadline_s=1.0)
    assert transport.calls == calls
    assert warnings(caplog) == [WARN_PREFIX + UNOBSERVABLE.format("search('q')")]


def test_a_search_failure_is_refused_not_read_as_not_listed(caplog):
    client, transport = sdk([reply(500, text="boom"), listing("m-1")])
    with patch("httpx.Client.request", new=transport), pytest.raises(PublicWaitRefused):
        drive(observe_search(client, "q", "m-1"), wait="stored", deadline_s=1.0)
    assert transport.calls == 1
    assert warnings(caplog) == [
        WARN_PREFIX + "search('q') failed (SmartMemoryServerError: boom)"
    ]


def test_a_search_that_is_not_a_list_is_refused(caplog):
    stub = SimpleNamespace(search=lambda query, **kw: {"decision": []})
    with pytest.raises(PublicWaitRefused):
        drive(observe_search(stub, "q", "m-1"), wait="stored", deadline_s=1.0)
    assert warnings(caplog) == [WARN_PREFIX + "search('q') returned dict, not a list"]


def _status(extraction, stage, execution, outcome):
    return {
        **ITEM,
        "read_status": {
            "extraction_state": extraction,
            "processing_stage": stage,
            "execution_state": execution,
            "outcome": outcome,
            "revision": 1,
        },
    }


def _real(payload):
    """A real ``httpx.Response(200)`` so the SDK's own parsing, not a mock, decides what survives."""
    return httpx.Response(
        200, json=payload, request=httpx.Request("GET", BASE_URL + "/memory/m-1")
    )


FAILED_ROW = _status("failed", "stored", "failed", "failed")
QUEUED_ROW = _status("extraction_pending", "received", "queued", None)
GAP = pytest.mark.xfail(
    strict=True,
    raises=PublicWaitRefused,
    reason="C49-SDK-STATUS-1 (filed 2026-10-17, unscheduled): the SDK drops read_status from get and search rows",
)
# id, family, response row, wait, expected outcome. Each row is what the owning unit must make true: the SDK read
# keeps the service's status, so a failed run is `failed` and a queued one is still pending, never `stored`.
FAILED_THROUGH_SDK = [
    pytest.param(
        "get", FAILED_ROW, "stored", "failed", id="get: a failed run", marks=GAP
    ),
    pytest.param(
        "search", FAILED_ROW, "stored", "failed", id="search: a failed run", marks=GAP
    ),
    pytest.param(
        "get",
        QUEUED_ROW,
        "stored",
        "client_timed_out",
        id="get: a queued run is not stored",
        marks=GAP,
    ),
    pytest.param(
        "search",
        QUEUED_ROW,
        "stored",
        "client_timed_out",
        id="search: a queued run is not stored",
        marks=GAP,
    ),
]


@pytest.mark.parametrize(("family", "payload", "wait", "outcome"), FAILED_THROUGH_SDK)
def test_the_sdk_read_keeps_the_run_status_the_service_sent(
    family, payload, wait, outcome
):
    client = SmartMemoryClient(base_url=BASE_URL, api_key="test_token_abc123")
    body = payload if family == "get" else {"results": [payload], "group_roots": []}
    observe = (
        observe_get(client, "m-1")
        if family == "get"
        else observe_search(client, "q", "m-1")
    )
    with patch("httpx.Client.request", new=Transport([_real(body)])):
        result, _ = drive(observe, wait=wait, deadline_s=0)
    assert result.outcome == outcome


# id, family, expected refusal message
REAL_FAILED_ROWS = [
    ("get", "get", UNOBSERVABLE.format("get('m-1')")),
    ("search", "search", UNOBSERVABLE.format("search('q')")),
]


@pytest.mark.parametrize("row", REAL_FAILED_ROWS, ids=[r[0] for r in REAL_FAILED_ROWS])
def test_a_failed_row_through_the_real_sdk_is_never_reported_stored(row, caplog):
    family, message = row[1], row[2]
    client = SmartMemoryClient(base_url=BASE_URL, api_key="test_token_abc123")
    body = (
        FAILED_ROW if family == "get" else {"results": [FAILED_ROW], "group_roots": []}
    )
    observe = (
        observe_get(client, "m-1")
        if family == "get"
        else observe_search(client, "q", "m-1")
    )
    with (
        patch("httpx.Client.request", new=Transport([_real(body)])),
        pytest.raises(PublicWaitStatusUnobservable),
    ):
        drive(observe, wait="stored", deadline_s=0)
    assert warnings(caplog) == [WARN_PREFIX + message]


def test_the_sdk_gap_is_pinned_and_fails_when_the_carrier_arrives():
    """C-01.activate.save.hosted-adapters (ring 3) owns the receipt/status SDK. Until then only 'stored' is observable."""
    fields = {f.name for f in dataclasses.fields(MemoryItem)}
    item = MemoryItem.from_dict(
        {**ITEM, "read_status": {"extraction_state": "extracted"}}
    )
    assert "read_status" not in fields and not hasattr(item, "read_status"), (
        "the SDK now carries read_status: extend observe_get to read it and drop the unobservable refusal"
    )


def test_the_legacy_direct_read_is_unchanged_and_no_sdk_api_was_added():
    client, transport = sdk([NOT_FOUND, FOUND])
    with patch("httpx.Client.request", new=transport):
        with pytest.raises(SmartMemoryNotFoundError):
            client.get("m-1")
        assert client.get("m-1").item_id == "m-1"
    assert transport.calls == 2
    assert wait_api_names(SmartMemoryClient) == ["await_receipt"]  # G53: by name only
    exported = [n for n in smartmemory_client.__all__ if "wait" in n.lower()]
    assert exported == []


def wait_api_names(cls):
    return sorted(n for n in dir(cls) if n.startswith(("wait", "await", "poll")))


def test_the_wait_api_guard_refuses_any_extra_wait_name(monkeypatch):
    monkeypatch.setattr(
        SmartMemoryClient, "poll_receipt", lambda self: None, raising=False
    )
    assert wait_api_names(SmartMemoryClient) != ["await_receipt"]


def test_a_5xx_on_the_legacy_direct_read_still_raises_the_typed_error():
    client, transport = sdk([reply(500, text="boom")])
    with (
        patch("httpx.Client.request", new=transport),
        pytest.raises(SmartMemoryServerError),
    ):
        client.get("m-1")
    assert transport.calls == 1
