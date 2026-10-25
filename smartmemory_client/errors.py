"""SmartMemory client exceptions.

The five HTTP-status classes lived in ``client.py`` and are re-exported from it, so
``from smartmemory_client.client import SmartMemoryClientError`` keeps working. The receipt,
conflict and stage-chain errors (REL-CALLERS-PYSDK-1) are here so ``receipt.py`` can raise them
without importing the client.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class SmartMemoryClientError(Exception):
    """Base exception for SmartMemory client errors.

    Subclasses (raised by the SDK on HTTP-status errors) expose:
        status_code (int | None): the HTTP status the server returned, if any.
        detail (str): the response body (best-effort).

    Every error also carries three optional fields the save path fills in:
        retry_after_s (float | None): the server's ``Retry-After``, in seconds.
        idempotency_key (str | None): the key of the save that failed, so an explicit
            later retry can send the same key and the same body.
        attempts (int | None): how many automatic attempts were made.

    Catching ``SmartMemoryClientError`` continues to handle every typed
    subclass for backwards compatibility.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str | None = None,
        *,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or ""
        self.retry_after_s = retry_after_s
        self.idempotency_key: Optional[str] = None
        self.attempts: Optional[int] = None


class SmartMemoryNotFoundError(SmartMemoryClientError):
    """Raised on HTTP 404 — the requested resource does not exist."""


class SmartMemoryPermissionError(SmartMemoryClientError):
    """Raised on HTTP 401/403 — auth missing, expired, or insufficient."""


class SmartMemoryValidationError(SmartMemoryClientError):
    """Raised on HTTP 400/409/422 — request shape or state was rejected."""


class SmartMemoryServerError(SmartMemoryClientError):
    """Raised on HTTP 5xx — the server failed to process the request."""


class SmartMemoryTransportError(SmartMemoryClientError):
    """Raised when the request never got an HTTP answer (connection lost, timeout).

    This is the "transport loss" the save retry policy (ST14) retries with the same key.
    """


class ReceiptError(SmartMemoryClientError):
    """The server answered, but the body is not a receipt this client can read as success.

    ``code`` is one of ``unsupported_version`` (major other than 1), ``unsupported_subject``,
    ``unsupported_state`` (an enum value this reader does not know), ``malformed_receipt`` (a required
    field is missing or has the wrong type) or ``not_a_receipt`` (a legacy projection or an old-style body).
    The handle survives: ``run_id`` and ``status_url`` are filled whenever the body carried them, and
    ``raw`` is the decoded body, so a caller can keep polling or show the opaque value. Never success.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        run_id: Optional[str] = None,
        status_url: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
        opaque: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.run_id = run_id
        self.status_url = status_url
        self.raw = raw or {}
        self.opaque = opaque or {}


class SaveConflictError(SmartMemoryValidationError):
    """HTTP 409 on a save or an edit: the scoped admission conflict, no new run was created.

    ``code`` is the contract's ``admission_error.code`` (``revision_conflict``, ``idempotency_conflict`` or
    ``retry_key_expired``), or ``None`` when the 409 body carried none (a WARNING is logged). A revision
    conflict also exposes ``expected_revision`` and ``current_revision``. The caller keeps its draft;
    the SDK never retries a 409 and never mints a new key.
    """

    code: Optional[str] = None

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: int | None = 409,
        detail: str | None = None,
        expected_revision: Any = None,
        current_revision: Any = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code=status_code, detail=detail)
        self.code = code
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        self.body = body or {}


class RevisionConflictError(SaveConflictError):
    """The item changed since ``expected_revision`` (G131). Review the current version before editing."""


class IdempotencyConflictError(SaveConflictError):
    """The retry key is bound to a different request."""


class RetryKeyExpiredError(SaveConflictError):
    """The 30-day retry key binding expired (G178). Keep the draft and ask before saving as new."""


#: Public stage-chain codes (ST33, ``save-read-client-contract.json#/$defs/stage_client_error``).
STAGE_CHAIN_CODES = (
    "stage_result_pending",
    "stage_result_expired",
    "stage_result_unavailable",
    "stage_chain_invalid",
    "stage_scope_denied",
    "unsupported_receipt_version",
)


class StageChainError(SmartMemoryClientError):
    """A public stage call cannot chain from the predecessor it was given (ST33, G169).

    ``code`` is one of ``STAGE_CHAIN_CODES``. ``run_id`` is the predecessor's receipt run when it may be
    disclosed (``None`` when hidden). A failed job's own receipt ``error.code`` is never overwritten by this.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        run_id: Optional[str] = None,
        retryable: bool = False,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, detail=detail)
        if code not in STAGE_CHAIN_CODES:
            raise ValueError(f"unknown stage chain code {code!r}")
        self.code = code
        self.run_id = run_id
        self.retryable = retryable
