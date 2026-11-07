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
    WriteOutcomeUnknown,
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


def is_safe_write_retry(exc: BaseException) -> bool:
    """Only a 429 refusal or a proven connect-phase failure may repeat an unreplayed write."""
    if isinstance(exc, SmartMemoryClientError) and exc.status_code == 429:
        return True
    # _request wraps httpx failures, retaining the concrete transport failure as its cause.
    # Read/write/pool timeouts and generic connection loss do not prove nothing was committed.
    transport = exc.__cause__ if isinstance(exc, SmartMemoryClientError) else exc
    return isinstance(transport, (httpx.ConnectError, httpx.ConnectTimeout))


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
    retry_safe: bool = True,
    deadline_s: float = AWAIT_TIMEOUT_S,
    before_retry: Optional[Callable[[], None]] = None,
    monotonic: Optional[Callable[[], float]] = None,
    sleep: Optional[Callable[[float], None]] = None,
    rng: Optional[Callable[[float, float], float]] = None,
) -> Any:
    """Retry a write only after 429 or a proven connect-phase failure, keeping body and key.

    Hosted 2.0.0 does not replay request keys yet (SVC-2.0-SAVE-KEY-REPLAY-1).
    Ambiguous failures surface once with ``idempotency_key`` and ``attempts``.
    ``retry_safe=False`` retains the add-specific ``WriteOutcomeUnknown`` on ambiguous outcomes.
    Check existing records before retrying. Read polling retains its broader retry policy.
