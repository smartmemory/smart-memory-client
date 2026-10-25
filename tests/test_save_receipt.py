"""REL-CALLERS-PYSDK-1: the 2.0 save receipt, the ST14 retry policy, the G53 await and the G131 edit precondition.

Wire shapes come from ``tests/data/save_receipt_fixtures.json`` (verbatim copies of the frozen
``save-receipt-contract.json`` examples and reader fixtures). The transport is a fake ``_request``: the
producers (service ``wait=``, ``/memory/status/{run_id}``, ``expected_revision``) had not landed when this was written.
"""

import copy
import inspect
import json
import logging
import re
from pathlib import Path

import httpx
import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client import _save_transport as transport
from smartmemory_client.client import _exception_for_status
from smartmemory_client.errors import (
    IdempotencyConflictError,
    ReceiptError,
    RetryKeyExpiredError,
    RevisionConflictError,
    SaveConflictError,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryTransportError,
    SmartMemoryValidationError,
    StageChainError,
)
from smartmemory_client.receipt import Receipt, parse_receipt

FX = json.loads(
    (Path(__file__).parent / "data" / "save_receipt_fixtures.json").read_text()
)
KEY_RE = re.compile(
    r"^sm2_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def http(status, body=None, retry_after=None):
    cls = _exception_for_status(status)
    detail = json.dumps(body) if body is not None else ""
    return cls(
        f"Request failed: HTTP {status}",
        status_code=status,
        detail=detail,
        retry_after_s=retry_after,
    )


def lost():
    return SmartMemoryTransportError("Request failed: connection lost")


class FakeTransport:
    """Replays a script of wire dicts and exceptions; the last entry repeats. Records every request."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, method, endpoint, params=None, json_body=None, **_):
        self.calls.append(
            (method, endpoint, copy.deepcopy(params), copy.deepcopy(json_body))
        )
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, BaseException):
            raise item
        return copy.deepcopy(item)


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 1000.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(transport.time, "monotonic", c.monotonic)
    monkeypatch.setattr(transport.time, "sleep", c.sleep)
    monkeypatch.setattr(
        transport.random, "uniform", lambda lo, hi: hi
    )  # full jitter window, deterministic
    return c


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://test", api_key="k", workspace_id="w")


def wired(client, monkeypatch, *script):
    fake = FakeTransport(*script)
    monkeypatch.setattr(client, "_request", fake)
    return fake


def variant(wire, **changes):
    out = copy.deepcopy(wire)
    for name, value in changes.items():
        if value is ...:
            out.pop(name, None)
        else:
            out[name] = value
    return out


PENDING, EXTRACTED, STAGE_DONE = (
    FX["pending_save"],
    FX["extracted_save"],
    FX["stage_job_completed"],
)
FUTURE_MINOR, FUTURE_SUBJECT, FUTURE_STATE = (
    FX["reader_fixtures"][0]["wire"],
    FX["reader_fixtures"][1]["wire"],
    FX["reader_fixtures"][2]["wire"],
)


# ---- the reader (G52, x-reader-decoder) ------------------------------------------------------------------------


def test_the_pending_save_receipt_reads_as_a_typed_object():
    r = parse_receipt(PENDING)
    assert isinstance(r, Receipt) and not isinstance(r, str)
    assert (r.item_id, r.run_id, r.status_url, r.revision) == (
        "mem_123",
        "run_1",
        "/memory/status/run_1",
        1,
    )
    assert (
        r.terminal,
        r.result_availability,
        r.client_timed_out,
        r.processing_stage,
    ) == (False, "pending", False, "received")


def test_a_terminal_save_receipt_carries_its_result_with_attribute_access():
    r = parse_receipt(EXTRACTED)
    assert (
        r.terminal
        and r.outcome == "completed"
        and r.result.revision == 1
        and r.result["item_id"] == "mem_123"
    )


def test_a_stage_job_receipt_has_no_item_and_no_processing_stage():
    r = parse_receipt(STAGE_DONE)
    assert (r.item_id, r.processing_stage, r.subject_kind) == (None, None, "stage_job")
    assert (
        r.result.pipeline_state_run_id == "pipeline_1"
        and r.result.stage_id == "extraction"
    )


# row id, wire, expected ReceiptError.code, expected handle run_id (None: no handle in the body)
READER_REFUSALS = [
    ("major 2", variant(PENDING, schema_version="2.0"), "unsupported_version", "run_1"),
    (
        "unknown subject kind (fixture)",
        FUTURE_SUBJECT,
        "unsupported_subject",
        "run_future_2",
    ),
    (
        "unknown stage/state/reason (fixture)",
        FUTURE_STATE,
        "unsupported_state",
        "run_future_3",
    ),
    ("old-style id body", {"id": "mem_1"}, "not_a_receipt", None),
    (
        "legacy projection",
        {
            "schema_version": "1.1",
            "projection_kind": "legacy_item_projection",
            "item_id": "m",
            "revision": 7,
            "status_provenance": "unknown",
        },
        "not_a_receipt",
        None,
    ),
    ("no run_id", variant(PENDING, run_id=...), "malformed_receipt", None),
    ("no terminal flag", variant(PENDING, terminal=...), "malformed_receipt", "run_1"),
    (
        "unreadable version",
        variant(PENDING, schema_version="x.y"),
        "malformed_receipt",
        "run_1",
    ),
    ("not an object", ["a"], "not_a_receipt", None),
]


def test_a_body_the_reader_cannot_take_as_success_is_a_typed_refusal_that_keeps_the_handle(
    caplog,
):
    for name, wire, code, run_id in READER_REFUSALS:
        caplog.clear()
        with (
            caplog.at_level(logging.WARNING, logger="smartmemory_client.receipt"),
            pytest.raises(ReceiptError) as exc,
        ):
            parse_receipt(wire)
        assert (exc.value.code, exc.value.run_id) == (code, run_id), name
        assert "receipt refused" in caplog.text, (
            name
        )  # no silent degradation: one WARNING naming what was lost


def test_an_unknown_state_keeps_its_opaque_value_and_status_url():
    with pytest.raises(ReceiptError) as exc:
        parse_receipt(FUTURE_STATE)
    assert (
        exc.value.opaque["processing_stage"] == "future_stage"
        and exc.value.status_url == "/memory/status/run_future_3"
    )


def test_a_future_minor_with_an_unknown_nested_field_is_known_pending_with_the_field_kept():
    r = parse_receipt(FUTURE_MINOR)
    assert (r.schema_version, r.terminal, r.run_id) == ("1.2", False, "run_future_1")
    assert (
        r.context.future_field == "opaque"
        and r.raw["context"]["future_field"] == "opaque"
    )


def test_a_document_save_reports_its_document_id_as_the_item_id():
    wire = variant(PENDING, subject={"kind": "document_save", "document_id": "doc_9"})
    assert parse_receipt(wire).item_id == "doc_9"


# ---- add / ingest return the receipt; ingest_full is gone (G52, G51) -------------------------------------------


def test_add_returns_the_receipt_and_sends_one_minted_key(client, monkeypatch):
    fake = wired(client, monkeypatch, PENDING)
    r = client.add("x")
    assert (r.item_id, r.run_id, r.revision) == (
        "mem_123",
        "run_1",
        1,
    ) and not isinstance(r, str)
    method, endpoint, _, body = fake.calls[0]
    assert (method, endpoint) == ("POST", "/memory/add") and KEY_RE.match(
        body["idempotency_key"]
    )


def test_a_future_major_through_add_raises_the_typed_error_with_the_handle(
    client, monkeypatch
):
    wired(client, monkeypatch, variant(PENDING, schema_version="2.0"))
    with pytest.raises(ReceiptError) as exc:
        client.add("x")
    assert (exc.value.code, exc.value.run_id) == ("unsupported_version", "run_1")


def test_an_empty_save_answer_is_a_typed_error_not_a_receipt(client, monkeypatch):
    wired(client, monkeypatch, None)
    with pytest.raises(SmartMemoryClientError, match="empty body"):
        client.add("x")


def test_ingest_with_wait_extracted_replaces_ingest_full(client, monkeypatch):
    fake = wired(client, monkeypatch, EXTRACTED)
    r = client.ingest("x", wait="extracted")
    _, endpoint, _, body = fake.calls[0]
    assert (endpoint, body["wait"]) == (
        "/memory/ingest",
        "extracted",
    ) and r.result.item_id == "mem_123"
    assert not hasattr(SmartMemoryClient, "ingest_full")


def test_ingest_omits_wait_when_unset_and_refuses_an_unknown_wait_before_sending(
    client, monkeypatch
):
    fake = wired(client, monkeypatch, PENDING)
    client.ingest("x")
    assert "wait" not in fake.calls[0][3]
    with pytest.raises(SmartMemoryValidationError):
        client.ingest("x", wait="done")
    assert len(fake.calls) == 1


# ---- ST14 retry policy ------------------------------------------------------------------------------------------

OTHER_STATUS_REFUSED = (400, 401, 403, 404, 422)
RETRYABLE = (408, 429, 500, 502, 503, 504)


def test_three_transport_losses_then_success_is_four_identical_requests(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, lost(), lost(), lost(), PENDING)
    assert client.add("x").run_id == "run_1"
    assert len(fake.calls) == 4
    keys = {c[3]["idempotency_key"] for c in fake.calls}
    bodies = {json.dumps(c[3], sort_keys=True) for c in fake.calls}
    assert len(keys) == 1 and KEY_RE.match(keys.pop()) and len(bodies) == 1
    assert clock.sleeps == [
        0.2,
        0.4,
        0.8,
    ]  # full-jitter windows, upper edge under the patched rng


def test_a_fake_that_always_fails_gets_exactly_four_attempts_then_the_typed_error_with_the_key(
    client, monkeypatch, clock
):
    rows = [("lost", lost())] + [(f"HTTP {s}", http(s)) for s in RETRYABLE]
    for name, failure in rows:
        fake = wired(client, monkeypatch, failure)
        with pytest.raises(SmartMemoryClientError) as exc:
            client.add("x")
        assert len(fake.calls) == 4, name
        assert exc.value.attempts == 4 and KEY_RE.match(exc.value.idempotency_key), name


def test_statuses_outside_the_retry_list_are_one_request_and_never_a_new_key(
    client, monkeypatch, clock
):
    for status in OTHER_STATUS_REFUSED + (409,):
        fake = wired(client, monkeypatch, http(status))
        with pytest.raises(SmartMemoryClientError) as exc:
            client.add("x")
        assert (
            len(fake.calls) == 1 and exc.value.attempts == 1 and clock.sleeps == []
        ), status


def test_a_retry_after_is_a_minimum_delay_and_one_that_cannot_fit_stops_the_retries(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, http(503, retry_after=2.0), PENDING)
    client.add("x")
    assert (len(fake.calls), clock.sleeps) == (2, [2.0])
    fake = wired(client, monkeypatch, http(429, retry_after=120.0), PENDING)
    with pytest.raises(SmartMemoryClientError) as exc:
        client.add("x")
    assert (
        len(fake.calls) == 1
        and exc.value.status_code == 429
        and KEY_RE.match(exc.value.idempotency_key)
    )


def test_a_raw_connection_error_is_transport_loss_and_comes_back_typed(
    client, monkeypatch, clock
):
    for failure in (
        ConnectionError("reset"),
        httpx.ConnectError("refused"),
        TimeoutError("slow"),
    ):
        fake = wired(client, monkeypatch, failure)
        with pytest.raises(SmartMemoryTransportError) as exc:
            client.add("x")
        assert len(fake.calls) == 4 and isinstance(exc.value.__cause__, type(failure))


def test_a_status_less_error_with_no_transport_cause_is_not_retried(
    client, monkeypatch, clock
):
    fake = wired(
        client, monkeypatch, SmartMemoryClientError("Request failed: bad json")
    )
    with pytest.raises(SmartMemoryClientError):
        client.add("x")
    assert len(fake.calls) == 1


def test_a_caller_key_is_kept_and_a_malformed_key_is_refused_before_any_request(
    client, monkeypatch
):
    fake = wired(client, monkeypatch, PENDING)
    client.add("x", idempotency_key="draft_1:retry")
    assert fake.calls[0][3]["idempotency_key"] == "draft_1:retry"
    for bad in ("", "has space", "x" * 129):
        with pytest.raises(SmartMemoryValidationError):
            client.add("x", idempotency_key=bad)
    assert len(fake.calls) == 1


# ---- typed conflicts (G131, G178) -------------------------------------------------------------------------------

REVISION_409 = {
    "schema_version": "1.1",
    "admission_error": {"code": "revision_conflict", "message": "changed"},
    "expected_revision": 1,
    "current_revision": 2,
}
# row id, body, expected class, expected code
CONFLICT_ROWS = [
    ("revision", REVISION_409, RevisionConflictError, "revision_conflict"),
    (
        "key bound elsewhere",
        FX["idempotency_conflict"],
        IdempotencyConflictError,
        "idempotency_conflict",
    ),
    ("key expired", FX["expired_key"], RetryKeyExpiredError, "retry_key_expired"),
    ("no scoped code", {"detail": "conflict"}, SaveConflictError, None),
    ("unparseable body", None, SaveConflictError, None),
]


def test_a_409_on_a_save_is_the_typed_scoped_conflict_with_one_request(
    client, monkeypatch, clock, caplog
):
    for name, body, cls, code in CONFLICT_ROWS:
        fake = wired(client, monkeypatch, http(409, body))
        caplog.clear()
        with (
            caplog.at_level(
                logging.WARNING, logger="smartmemory_client._save_transport"
            ),
            pytest.raises(cls) as exc,
        ):
            client.add("x")
        assert exc.value.code == code and isinstance(
            exc.value, SmartMemoryValidationError
        ), name
        assert len(fake.calls) == 1 and KEY_RE.match(exc.value.idempotency_key), name
        assert ("scoped conflict code is lost" in caplog.text) == (code is None), name


# ---- G131 edit precondition ------------------------------------------------------------------------------------


def test_update_sends_expected_revision_only_when_given(client, monkeypatch):
    fake = wired(client, monkeypatch, None)
    client.update("mem_123", content="y")
    client.update("mem_123", content="y", expected_revision=1)
    assert "expected_revision" not in fake.calls[0][3]
    assert (
        fake.calls[1][:2] == ("PATCH", "/memory/mem_123")
        and fake.calls[1][3]["expected_revision"] == 1
    )


def test_a_stale_edit_is_one_typed_conflict_with_both_revisions_and_no_retry(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, http(409, REVISION_409))
    with pytest.raises(RevisionConflictError) as exc:
        client.update("mem_123", content="y", expected_revision=1)
    assert (
        len(fake.calls),
        exc.value.expected_revision,
        exc.value.current_revision,
    ) == (1, 1, 2)
    assert clock.sleeps == []


def test_update_returns_the_edit_receipt_and_warns_when_a_precondition_got_none(
    client, monkeypatch, caplog
):
    edit = variant(PENDING, subject={"kind": "edit", "item_id": "mem_123"})
    wired(client, monkeypatch, edit)
    assert (
        client.update("mem_123", content="y", expected_revision=1).subject_kind
        == "edit"
    )
    wired(client, monkeypatch, None)
    with caplog.at_level(logging.WARNING, logger="smartmemory_client.client"):
        assert client.update("mem_123", content="y", expected_revision=1) is None
    assert "precondition may not have been enforced" in caplog.text


def test_other_update_failures_stay_the_old_typed_errors(client, monkeypatch):
    wired(client, monkeypatch, http(404))
    with pytest.raises(SmartMemoryNotFoundError):
        client.update("mem_123", content="y", expected_revision=1)


# ---- G53/G173 await ---------------------------------------------------------------------------------------------


def test_a_terminal_receipt_returns_with_no_request(client, monkeypatch, clock):
    fake = wired(client, monkeypatch, EXTRACTED)
    r = parse_receipt(EXTRACTED)
    assert client.await_receipt(r) is r and fake.calls == []


def test_a_pending_receipt_that_is_terminal_on_the_first_read_costs_one_request_and_no_sleep(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, EXTRACTED)
    r = client.await_receipt(parse_receipt(PENDING))
    assert (
        r.terminal
        and r.result.revision == 1
        and len(fake.calls) == 1
        and clock.sleeps == []
    )
    method, path, params, _ = fake.calls[0]
    assert (method, path, params["target"]) == (
        "GET",
        "/memory/status/run_1",
        "terminal",
    )


def test_a_receipt_that_never_turns_terminal_comes_back_pending_and_flagged_at_the_deadline(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, PENDING)
    r = client.await_receipt(parse_receipt(PENDING), timeout=0.5)
    assert (r.client_timed_out, r.terminal, r.run_id) == (True, False, "run_1")
    assert 1 < len(fake.calls) < 8 and 0.5 <= clock.now - 1000.0 <= 0.5 + 0.01
    assert all(
        0.25 <= s <= 5.0 for s in clock.sleeps[:-1]
    )  # the last sleep is clipped to the time left


def test_poll_backoff_grows_from_250ms_to_the_5s_cap(client, monkeypatch, clock):
    wired(client, monkeypatch, PENDING)
    client.await_receipt(parse_receipt(PENDING), timeout=60.0)
    assert clock.sleeps[0] == pytest.approx(0.25 * 1.2) and max(clock.sleeps) == 5.0
    assert clock.sleeps[:-1] == sorted(
        clock.sleeps[:-1]
    )  # the last sleep is clipped to the time left


def test_a_stored_target_is_met_by_a_stored_receipt_without_waiting_for_terminal(
    client, monkeypatch, clock
):
    stored = variant(
        PENDING, processing_stage="stored", execution_state="running", status_version=2
    )
    fake = wired(client, monkeypatch, stored)
    r = client.await_receipt(parse_receipt(PENDING), target="stored")
    assert r.processing_stage == "stored" and not r.terminal and len(fake.calls) == 1


def test_failed_status_reads_back_off_inside_the_same_deadline_then_succeed(
    client, monkeypatch, clock
):
    fake = wired(
        client, monkeypatch, lost(), http(503), http(429, retry_after=1.0), EXTRACTED
    )
    r = client.await_receipt(parse_receipt(PENDING))
    assert r.terminal and len(fake.calls) == 4 and clock.sleeps[2] >= 1.0


def test_a_retry_after_that_cannot_fit_returns_pending_with_no_further_request(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, http(503, retry_after=99.0))
    r = client.await_receipt(parse_receipt(PENDING), timeout=5.0)
    assert (r.client_timed_out, len(fake.calls)) == (True, 1)


# One row per await-loop path that leaves the read branch: (label, script of held/error reads, timeout,
# expected request count, expected sleeps, client_timed_out). A held read advances the clock by its wait_ms
# (FakeClock has no read time), so the rows below fix the hold at the 10 s long-poll cap.
def _held(**changes):
    return variant(PENDING, **changes)


HELD_ROWS = [
    # the reviewer's M1: delay 99 s cannot fit the 20 s left after the first 10 s hold -> no further request
    ("held delay cannot fit", [_held(retry_after_ms=99000)], 30.0, 1, [], True),
    # a delay that fits is slept exactly (a minimum, no extra backoff), then the next read runs
    (
        "held delay fits",
        [_held(retry_after_ms=2000), EXTRACTED],
        30.0,
        2,
        [2.0],
        False,
    ),
    # no delay: the server already waited, so the next read goes at once with no sleep
    ("held no delay", [_held(), EXTRACTED], 30.0, 2, [], False),
    # reached target on a held read returns at once even with a delay on the wire
    (
        "held read reaches terminal",
        [variant(EXTRACTED, retry_after_ms=99000)],
        30.0,
        1,
        [],
        False,
    ),
    # sibling path: an error read with Retry-After that fits sleeps at least that long
    ("error delay fits", [http(503, retry_after=2.0), EXTRACTED], 30.0, 2, None, False),
]


@pytest.mark.parametrize(
    "label,script,timeout,requests,sleeps,timed_out",
    HELD_ROWS,
    ids=[r[0] for r in HELD_ROWS],
)
def test_held_and_failed_reads_honour_the_server_delay_and_the_deadline(
    client, monkeypatch, clock, label, script, timeout, requests, sleeps, timed_out
):
    inner = FakeTransport(*script)

    def fake(method, endpoint, params=None, json_body=None, **kw):
        out = inner(method, endpoint, params, json_body, **kw)
        if params and params.get("wait_ms") and not isinstance(out, BaseException):
            clock.now += (
                params["wait_ms"] / 1000
            )  # the server held the read for the full wait
        return out

    monkeypatch.setattr(client, "_request", fake)
    start = clock.now
    r = client.await_receipt(parse_receipt(PENDING), timeout=timeout)
    assert (len(inner.calls), r.client_timed_out) == (requests, timed_out), label
    if sleeps is not None:
        assert clock.sleeps == pytest.approx(sleeps), label
    else:
        assert clock.sleeps[0] >= 2.0, label
    assert clock.now - start <= timeout + 1e-6, label  # the deadline is never exceeded
    assert r.run_id == "run_1"


def test_a_missing_or_unreadable_status_raises_instead_of_looking_pending(
    client, monkeypatch, clock
):
    wired(client, monkeypatch, http(404))
    with pytest.raises(SmartMemoryNotFoundError):
        client.await_receipt(parse_receipt(PENDING))
    wired(client, monkeypatch, FUTURE_STATE)
    with pytest.raises(ReceiptError) as exc:
        client.await_receipt(parse_receipt(PENDING))
    assert exc.value.code == "unsupported_state" and exc.value.run_id == "run_future_3"


def test_a_lite_local_status_url_polls_the_standard_status_route(
    client, monkeypatch, clock
):
    fake = wired(client, monkeypatch, EXTRACTED)
    client.await_receipt(
        parse_receipt(variant(PENDING, status_url="local-status:run_1"))
    )
    assert fake.calls[0][1] == "/memory/status/run_1"


def test_an_unknown_await_target_is_refused_before_any_request(client, monkeypatch):
    fake = wired(client, monkeypatch, PENDING)
    with pytest.raises(SmartMemoryValidationError):
        client.await_receipt(parse_receipt(PENDING), target="done")
    assert fake.calls == []


# ---- G129 ------------------------------------------------------------------------------------------------------


def test_promote_no_longer_accepts_the_source_delete_option():
    assert (
        "remove_working_items"
        not in inspect.signature(
            SmartMemoryClient.promote_procedure_candidate
        ).parameters
    )


# ---- G169 / ST33 stage calls -----------------------------------------------------------------------------------

STAGE_PENDING = variant(
    STAGE_DONE,
    execution_state="queued",
    outcome=None,
    terminal=False,
    result_availability="pending",
    result=...,
)
STAGE_EXPIRED = variant(STAGE_DONE, result_availability="expired", result=...)
STAGE_FAILED = variant(
    STAGE_DONE,
    execution_state="failed",
    outcome="failed",
    result_availability="none",
    result=...,
)


def test_a_stage_call_returns_the_stage_job_receipt_not_a_result(client, monkeypatch):
    fake = wired(client, monkeypatch, STAGE_PENDING)
    receipt = client.run_extraction_stage("x")
    assert (receipt.run_id, receipt.processing_stage, receipt.terminal) == (
        "run_stage_1",
        None,
        False,
    )
    assert fake.calls[0][:2] == ("POST", "/memory/pipeline/extraction")


# one row per predecessor the chain can meet: (predecessor, code or None for accepted)
CHAIN_ROWS = [
    ("awaited receipt", STAGE_DONE, None),
    ("pending receipt", STAGE_PENDING, "stage_result_pending"),
    ("expired detail", STAGE_EXPIRED, "stage_result_expired"),
    ("failed, no result", STAGE_FAILED, "stage_result_unavailable"),
    ("an item save, not a stage", EXTRACTED, "stage_chain_invalid"),
]


@pytest.mark.parametrize("name,wire,code", CHAIN_ROWS, ids=[r[0] for r in CHAIN_ROWS])
def test_chaining_storage_from_a_receipt(client, monkeypatch, name, wire, code):
    fake = wired(client, monkeypatch, STAGE_PENDING)
    if code is None:
        client.run_storage_stage(parse_receipt(wire))
        assert fake.calls[0][3]["run_id"] == "pipeline_1"
        return
    with pytest.raises(StageChainError) as exc:
        client.run_storage_stage(parse_receipt(wire))
    assert (exc.value.code, exc.value.run_id, fake.calls) == (code, wire["run_id"], [])


def test_the_execution_run_id_is_never_a_chain_id_but_the_pipeline_state_id_is(
    client, monkeypatch, caplog
):
    fake = wired(client, monkeypatch, STAGE_PENDING)
    receipt = client.run_extraction_stage("x")
    with caplog.at_level(logging.WARNING), pytest.raises(StageChainError) as exc:
        client.run_storage_stage(receipt.run_id)
    assert (
        exc.value.code == "stage_chain_invalid"
        and "pipeline_state_run_id" in caplog.text
    )
    client.run_storage_stage("pipeline_1")
    assert [c[1] for c in fake.calls] == [
        "/memory/pipeline/extraction",
        "/memory/pipeline/storage",
    ]


def test_a_non_receipt_predecessor_is_refused(client, monkeypatch):
    wired(client, monkeypatch, STAGE_PENDING)
    with pytest.raises(StageChainError) as exc:
        client.run_storage_stage({"entities": []})
    assert exc.value.code == "stage_chain_invalid"


REFUSALS = [
    (409, {"code": "stage_result_pending"}, "stage_result_pending", True),
    (410, {"error": {"code": "stage_result_expired"}}, "stage_result_expired", False),
    (409, {"code": "stage_result_unavailable"}, "stage_result_unavailable", False),
    (409, {"code": "stage_chain_invalid"}, "stage_chain_invalid", False),
    (403, {"code": "stage_scope_denied"}, "stage_scope_denied", False),
]


@pytest.mark.parametrize(
    "status,body,code,retryable", REFUSALS, ids=[r[2] for r in REFUSALS]
)
def test_a_service_refusal_with_a_stage_code_is_a_typed_chain_error(
    client, monkeypatch, status, body, code, retryable
):
    fake = wired(client, monkeypatch, http(status, body))
    with pytest.raises(StageChainError) as exc:
        client.run_storage_stage("pipeline_1")
    assert (exc.value.code, exc.value.retryable, len(fake.calls)) == (
        code,
        retryable,
        1,
    )


def test_a_refusal_without_a_stage_code_stays_the_plain_http_error(client, monkeypatch):
    wired(client, monkeypatch, http(409, {"detail": "nope"}))
    with pytest.raises(SmartMemoryValidationError) as exc:
        client.run_storage_stage("pipeline_1")
    assert not isinstance(exc.value, StageChainError)


def test_a_future_major_stage_receipt_is_unsupported_receipt_version_with_its_handle(
    client, monkeypatch
):
    wired(client, monkeypatch, variant(STAGE_DONE, schema_version="2.0"))
    with pytest.raises(StageChainError) as exc:
        client.run_extraction_stage("x")
    assert (exc.value.code, exc.value.run_id) == (
        "unsupported_receipt_version",
        "run_stage_1",
    )
