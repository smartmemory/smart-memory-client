"""Save transport policy for the 2.0 receipt (ST14 retry, G53/G173 await).

Wire authority: ``save-read-client-spec.md`` ST14 and ``save-receipt-contract.json`` ``x-contract.await``.
Everything here is plain functions with injectable clock, sleep and jitter so tests run without waiting.
"""

from __future__ import annotations

import contextvars
import json
import logging
import random
import re
import time
import uuid
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import httpx

from smartmemory_client.errors import (
    STAGE_CHAIN_CODES,
    IdempotencyConflictError,
    RetryKeyExpiredError,
    RevisionConflictError,
    SaveConflictError,
    SmartMemoryClientError,
    SmartMemoryTransportError,
    SmartMemoryValidationError,
    StageChainError,
)
from smartmemory_client.receipt import (
    Receipt,
    legacy_no_status,
    parse_receipt,
    timed_out,
)

logger = logging.getLogger(__name__)

#: ST14: initial attempt plus three retries.
MAX_ATTEMPTS = 4
#: ST14: full jitter inside 0-200, 0-400, 0-800 ms before attempts 2, 3 and 4.
JITTER_WINDOWS_S = (0.2, 0.4, 0.8)
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
#: Retry-After is honoured as a minimum only on these.
RETRY_AFTER_STATUS = frozenset({429, 503})

#: ST14: caller-supplied keys, 1-128 characters.
KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

#: G53/G173: one monotonic deadline bounds the whole await.
AWAIT_TIMEOUT_S = 30.0
AWAIT_BACKOFF_MIN_S = 0.25
AWAIT_BACKOFF_MAX_S = 5.0
AWAIT_LONG_POLL_MAX_MS = 10_000

#: Set by ``await_receipt`` so one status read cannot outlive the await deadline (read by ``_request``).
REQUEST_TIMEOUT_S: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "smartmemory_request_timeout_s", default=None
)


def mint_key() -> str:
    """One ``idempotency_key`` per logical save: ``sm2_`` plus a lowercase hyphenated UUID v4."""
    return "sm2_" + str(uuid.uuid4())


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise SmartMemoryValidationError(
            "idempotency_key must be 1-128 characters from A-Z a-z 0-9 . _ : -",
            status_code=None,
        )
    return key


def is_transport_loss(exc: BaseException) -> bool:
    """True when the request never got an HTTP answer (the only non-status retry class)."""
    kinds = (
        SmartMemoryTransportError,
        httpx.TransportError,
        ConnectionError,
        TimeoutError,
    )
    if isinstance(exc, kinds):
        return True
    return (
        isinstance(exc, SmartMemoryClientError)
        and exc.status_code is None
        and isinstance(exc.__cause__, kinds)
    )


def is_retryable(exc: BaseException) -> bool:
    if is_transport_loss(exc):
        return True
    return (
        isinstance(exc, SmartMemoryClientError) and exc.status_code in RETRYABLE_STATUS
    )


def _annotate(exc: BaseException, key: Optional[str], attempts: int) -> BaseException:
    if not isinstance(exc, SmartMemoryClientError):
        wrapped = SmartMemoryTransportError(f"Request failed: {exc}")
        wrapped.__cause__ = exc
        exc = wrapped
    exc.idempotency_key = key
    exc.attempts = attempts
    return exc


def submit_with_retry(
    call: Callable[[], Any],
    *,
    key: Optional[str],
    deadline_s: float = AWAIT_TIMEOUT_S,
    monotonic: Optional[Callable[[], float]] = None,
    sleep: Optional[Callable[[float], None]] = None,
    rng: Optional[Callable[[float, float], float]] = None,
) -> Any:
    """Run one logical save with the ST14 policy: same key and same bytes on every attempt.

    ``call`` must send an identical request each time. A failure that is not retryable (400, 401, 403, 404,
    409, 422, anything outside the retry list) raises at once. After the fourth failed attempt, or when a
    ``Retry-After`` cannot fit in ``deadline_s``, the last error is raised carrying ``idempotency_key`` and
    ``attempts`` so a later explicit retry can reuse the key.
    """
    monotonic, sleep, rng = (
        monotonic or time.monotonic,
        sleep or time.sleep,
        rng or random.uniform,
    )
    started = monotonic()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - classified below, re-raised typed
            if not is_retryable(exc) or attempt == MAX_ATTEMPTS:
                annotated = _annotate(exc, key, attempt)
                if annotated is exc:
                    raise
                raise annotated from exc
            delay = rng(0.0, JITTER_WINDOWS_S[attempt - 1])
            status = getattr(exc, "status_code", None)
            retry_after = (
                getattr(exc, "retry_after_s", None)
                if status in RETRY_AFTER_STATUS
                else None
            )
            if retry_after is not None:
                if retry_after > deadline_s - (monotonic() - started):
                    logger.warning(
                        "save retry stopped: Retry-After %.1fs does not fit the %.1fs deadline; key %s kept",
                        retry_after,
                        deadline_s,
                        key,
                    )
                    annotated = _annotate(exc, key, attempt)
                    if annotated is exc:
                        raise
                    raise annotated from exc
                delay = max(delay, retry_after)
            logger.info(
                "save attempt %d/%d failed (%s); retrying with key %s",
                attempt,
                MAX_ATTEMPTS,
                _why(exc),
                key,
            )
            sleep(delay)
    raise AssertionError(
        "unreachable"
    )  # pragma: no cover - the loop always returns or raises


def _why(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    return f"HTTP {status}" if status else "transport loss"


def conflict_from(exc: SmartMemoryClientError) -> Optional[SaveConflictError]:
    """Turn a 409 into the typed scoped conflict, or ``None`` when ``exc`` is not a 409.

    The body's ``admission_error.code`` picks the subclass. A 409 whose body carries none still becomes a
    ``SaveConflictError`` (``code=None``) with one WARNING saying the scoped code was lost.
    """
    if exc.status_code != 409:
        return None
    body: Dict[str, Any] = {}
    try:
        parsed = json.loads(exc.detail) if exc.detail else {}
        body = parsed if isinstance(parsed, dict) else {}
    except ValueError:
        body = {}
    admission = body.get("admission_error")
    admission = admission if isinstance(admission, dict) else {}
    code = admission.get("code")
    cls = {
        "revision_conflict": RevisionConflictError,
        "idempotency_conflict": IdempotencyConflictError,
        "retry_key_expired": RetryKeyExpiredError,
    }.get(code, SaveConflictError)
    if cls is SaveConflictError:
        logger.warning(
            "409 body carried no known admission_error.code (got %r); the scoped conflict code is lost",
            code,
        )
        code = None
    message = admission.get("message") or str(exc)
    return cls(
        message,
        code=code,
        detail=exc.detail,
        expected_revision=body.get("expected_revision"),
        current_revision=body.get("current_revision"),
        body=body,
    )


def stage_chain_from(exc: SmartMemoryClientError) -> Optional[StageChainError]:
    """Turn a stage-submission refusal whose body names an ST33 code into ``StageChainError``, else ``None``.

    The code is read from ``code``, ``error.code`` or ``admission_error.code`` of the JSON body. A body with no
    known code is left as the original typed HTTP error (the caller re-raises it).
    """
    try:
        parsed = json.loads(exc.detail) if exc.detail else {}
    except ValueError:
        return None
    body = parsed if isinstance(parsed, dict) else {}
    code = body.get("code")
    for key in ("error", "admission_error", "detail"):
        nested = body.get(key)
        if code is None and isinstance(nested, dict):
            code = nested.get("code")
    if code not in STAGE_CHAIN_CODES:
        return None
    run_id = body.get("run_id")
    return StageChainError(
        str(body.get("message") or exc),
        code=code,
        run_id=run_id if isinstance(run_id, str) else None,
        retryable=code == "stage_result_pending",
        status_code=exc.status_code,
        detail=exc.detail,
    )


def chain_run_id(predecessor: Any, seen_receipt_runs: Any) -> str:
    """The ``pipeline_state_run_id`` a dependent stage submits, from a stage receipt or a bare id (ST33).

    A receipt must be a terminal ``available`` stage result; pending, expired, unavailable and
    wrong-version receipts raise the matching ``StageChainError`` instead of producing a false run id. A bare
    string is taken as an already-authorized ``pipeline_state_run_id`` unless it is the execution ``run_id`` of
    a receipt this client returned, which is never a valid chain id (``stage_chain_invalid``).
    """
    if isinstance(predecessor, str):
        if predecessor in seen_receipt_runs:
            logger.warning(
                "refused a stage chain from receipt run_id %s: pass result.pipeline_state_run_id",
                predecessor,
            )
            raise StageChainError(
                "receipt.run_id is the execution handle, not a pipeline state id: chain from "
                "receipt.result.pipeline_state_run_id",
                code="stage_chain_invalid",
                run_id=predecessor,
            )
        return predecessor
    if not isinstance(predecessor, Receipt):
        raise StageChainError(
            f"a stage chains from a stage Receipt or a pipeline_state_run_id string, not {type(predecessor).__name__}",
            code="stage_chain_invalid",
        )
    handle = predecessor.run_id
    if predecessor.subject.get("kind") != "stage_job":
        raise StageChainError(
            "the predecessor receipt is not a stage_job",
            code="stage_chain_invalid",
            run_id=handle,
        )
    if not predecessor.terminal:
        raise StageChainError(
            "the predecessor stage has not finished: await_receipt it first",
            code="stage_result_pending",
            run_id=handle,
            retryable=True,
        )
    if predecessor.result_availability == "expired":
        raise StageChainError(
            "the predecessor stage result expired: run the stage again",
            code="stage_result_expired",
            run_id=handle,
        )
    pipeline_run = (
        predecessor.result.get("pipeline_state_run_id") if predecessor.result else None
    )
    if (
        predecessor.result_availability != "available"
        or not isinstance(pipeline_run, str)
        or not pipeline_run
    ):
        raise StageChainError(
            f"the predecessor stage ended {predecessor.outcome or predecessor.execution_state} with no usable result",
            code="stage_result_unavailable",
            run_id=handle,
        )
    return pipeline_run


def status_path(receipt: Receipt) -> str:
    """The scoped status route: the receipt's own URL when it is a service path, else the standard route."""
    if receipt.legacy or receipt.run_id is None or receipt.status_url is None:
        raise legacy_no_status()  # TODO(SVC-INGEST-WAIT-STATUS-1): remove with the bridge
    if receipt.status_url.startswith("/"):
        return receipt.status_url
    return f"/memory/status/{quote(receipt.run_id, safe='')}"


def _reached(receipt: Receipt, target: str) -> bool:
    if receipt.terminal:
        return True
    if target == "stored":
        return receipt.processing_stage in ("stored", "extracted")
    if target == "extracted":
        return receipt.processing_stage == "extracted"
    return False


def await_receipt(
    read: Callable[[str, Dict[str, Any]], Any],
    receipt: Receipt,
    *,
    timeout: float = AWAIT_TIMEOUT_S,
    target: str = "terminal",
    long_poll_ms: int = AWAIT_LONG_POLL_MAX_MS,
    monotonic: Optional[Callable[[], float]] = None,
    sleep: Optional[Callable[[float], None]] = None,
    rng: Optional[Callable[[float, float], float]] = None,
) -> Receipt:
    """Poll ``receipt`` until ``target`` or terminal fate, or ``timeout`` seconds pass (G53/G173).

    Returns at once when the receipt already satisfies the target. On timeout it RETURNS the current pending
    receipt with ``client_timed_out=True`` (never raises for time, never drops the handle). A status read that
    fails with transport loss, 408, 429 or 5xx backs off 250 ms to 5 s with bounded jitter and tries again; any
    other failure (404, a receipt the reader refuses) propagates. ``Retry-After`` / ``retry_after_ms`` is a
    minimum delay, and one that cannot fit in the remaining time ends the await without another request.
    ``read(path, params)`` performs one scoped GET and returns the decoded JSON.
    """
    if target not in ("stored", "extracted", "terminal"):
        raise SmartMemoryValidationError(
            f"await target must be stored, extracted or terminal, got {target!r}"
        )
    monotonic, sleep, rng = (
        monotonic or time.monotonic,
        sleep or time.sleep,
        rng or random.uniform,
    )
    path = status_path(
        receipt
    )  # a legacy receipt has no handle: refuse before any wait
    deadline = monotonic() + timeout
    current = receipt
    streak = 0
    while not _reached(current, target):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return timed_out(current)
        params: Dict[str, Any] = {"target": target}
        hold_ms = min(long_poll_ms, AWAIT_LONG_POLL_MAX_MS, int(remaining * 1000))
        if hold_ms > 0:
            params["wait_ms"] = hold_ms
        if current.status_version is not None:
            params["since_version"] = current.status_version
        minimum = 0.0
        held = False
        began = monotonic()
        token = REQUEST_TIMEOUT_S.set(max(remaining, 0.001))
        before = current
        try:
            current = parse_receipt(read(path, params))
            held = hold_ms > 0 and (monotonic() - began) >= 0.5 * hold_ms / 1000
            if held or current.status_version != before.status_version:
                streak = 0
            else:
                streak += 1
            if current.retry_after_ms:
                minimum = current.retry_after_ms / 1000
            if held and not minimum:
                continue  # the server already waited; with no explicit delay another read can go at once
        except Exception as exc:  # noqa: BLE001 - only retryable failures are absorbed, the rest re-raise
            if not is_retryable(exc):
                raise
            streak += 1
            retry_after = getattr(exc, "retry_after_s", None)
            if (
                getattr(exc, "status_code", None) in RETRY_AFTER_STATUS
                and retry_after is not None
            ):
                minimum = retry_after
        finally:
            REQUEST_TIMEOUT_S.reset(token)
        if _reached(current, target):
            break
        remaining = deadline - monotonic()
        if minimum > remaining:
            return timed_out(current)
        if held:
            sleep(
                minimum
            )  # a held read needs no backoff, only the server's explicit minimum
            continue
        base = min(AWAIT_BACKOFF_MAX_S, AWAIT_BACKOFF_MIN_S * 2 ** max(streak - 1, 0))
        delay = min(
            AWAIT_BACKOFF_MAX_S,
            max(AWAIT_BACKOFF_MIN_S, base * rng(0.8, 1.2)),
            max(remaining, 0.0),
        )
        sleep(max(delay, minimum))
    return current
