"""The 2.0 save receipt (G52/G128): a typed reader for the frozen W0 wire.

Wire authority: ``smart-memory-docs/docs/features/SM2-SAVE-1/save-receipt-contract.json`` (``x-contract.compatibility``
and ``x-reader-decoder``). This module is the *reader*, not the producer's exact schema validator:

* any ``1.x`` minor is accepted and unknown optional fields stay available as opaque data (``Receipt.raw``,
  ``Receipt.context``);
* an unsupported major raises ``ReceiptError(code="unsupported_version")`` with the handle that could be decoded;
* an unknown subject kind raises ``unsupported_subject``, an unknown stage/execution/outcome/reason/availability
  value raises ``unsupported_state``; both carry ``run_id``/``status_url`` and the opaque value, never success;
* a body that is not a receipt (a legacy ``{"id": ...}`` answer, a ``legacy_item_projection``) raises
  ``not_a_receipt`` with one WARNING, so an old server can never look like a saved item.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional

from smartmemory_client.errors import ReceiptError

logger = logging.getLogger(__name__)

SUPPORTED_MAJOR = 1

PROCESSING_STAGES = frozenset({"received", "stored", "extracted"})
EXECUTION_STATES = frozenset(
    {"queued", "waiting", "running", "paused", "completed", "failed", "dead"}
)
OUTCOMES = frozenset({"completed", "skipped", "no_op", "partial", "failed", "dead"})
RESULT_AVAILABILITY = frozenset({"pending", "available", "expired", "none"})
REASONS = frozenset(
    {"allowance", "authority", "key_needed", "dependency", "retry_backoff"}
)

#: subject kind -> the id field its ``item_id`` view reads (None: the subject has no item identity).
_ITEM_ID_FIELD = {
    "item_save": "item_id",
    "document_save": "document_id",  # G114: a document parent's id is the same scoped item id
    "edit": "item_id",
    "generation_save": None,
    "manual_occurrence": None,
    "scheduled_occurrence": None,
    "stage_job": None,
    "system_job": None,
}
SUBJECT_KINDS = frozenset(_ITEM_ID_FIELD)


class AttrDict(dict):
    """A decoded JSON object that also answers attribute reads (``result.pipeline_state_run_id``)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return AttrDict({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


@dataclass(frozen=True)
class Receipt:
    """What a 2.0 save, edit, document save or public stage call returns.

    ``item_id`` is the saved item's handle (``None`` for a stage or job receipt). ``run_id`` and ``status_url``
    are the poll handle, never an authorization token. ``terminal`` is true only once the fate is committed;
    ``client_timed_out`` is set by :meth:`SmartMemoryClient.await_receipt` when its deadline passed first, and
    says nothing about the server run. ``result`` is present when ``result_availability == "available"``.
    """

    schema_version: str
    subject: AttrDict
    run_id: Optional[str]
    status_url: Optional[str]
    processing_stage: Optional[str]
    execution_state: Optional[str]
    outcome: Optional[str]
    terminal: bool
    result_availability: str
    client_timed_out: bool = False
    revision: Any = None
    intake_id: Optional[str] = None
    reason: Optional[str] = None
    result: Optional[AttrDict] = None
    error: Optional[AttrDict] = None
    retry_after_ms: Optional[int] = None
    idempotency_key: Optional[str] = None
    status_version: Optional[int] = None
    execution_epoch: Optional[int] = None
    expected_revision: Any = None
    current_revision: Any = None
    placement: Optional[str] = None
    context: Optional[AttrDict] = None
    raw: AttrDict = field(default_factory=AttrDict, compare=False, repr=False)
    #: True for a pre-receipt add/ingest 2xx body read by the bridge: stored, no run to poll.
    #: TODO(SVC-INGEST-WAIT-STATUS-1): remove with the bridge.
    legacy: bool = False
    legacy_status: Optional[str] = None

    @property
    def item_id(self) -> Optional[str]:
        name = _ITEM_ID_FIELD.get(self.subject.get("kind"))
        return self.subject.get(name) if name else None

    @property
    def subject_kind(self) -> str:
        return self.subject["kind"]

    @property
    def pending(self) -> bool:
        return not self.terminal


def _handle(wire: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    run_id, status_url = wire.get("run_id"), wire.get("status_url")
    return {
        "run_id": run_id if isinstance(run_id, str) else None,
        "status_url": status_url if isinstance(status_url, str) else None,
    }


def _refuse(
    code: str, message: str, wire: Mapping[str, Any], **opaque: Any
) -> ReceiptError:
    logger.warning(
        "receipt refused (%s): %s; keeping handle run_id=%s",
        code,
        message,
        wire.get("run_id"),
    )
    return ReceiptError(
        message, code=code, raw=dict(wire), opaque=opaque, **_handle(wire)
    )


#: ``status`` values of the legacy add/ingest 2xx bodies that mean the item is stored. ``held``, ``error``,
#: ``failed``, ``success``, ``queued`` and anything else are never a stored save.
#: TODO(SVC-INGEST-WAIT-STATUS-1): delete this bridge when the hosted receipt producer lands.
_LEGACY_STORED_STATUS = frozenset({"created", "unchanged", "replaced"})
_legacy_warned = False


def _legacy_item_id(wire: Mapping[str, Any]) -> Optional[str]:
    """The item id of a legacy add/ingest save body, recognised by its exact keys, else ``None``.

    A non-empty string ``id`` (add) or ``item_id`` (ingest), none of the receipt's own
    ``schema_version``/``subject``/``status_url``, and a ``run_id`` that is absent, null or a string (a legacy
    ingest ``run_id`` is never followed). ``status`` must be ``created|unchanged|replaced``; it may be absent
    only for the ingest content-hash duplicate (``item_id`` with ``run_id: null`` and no ``status``).
    TODO(SVC-INGEST-WAIT-STATUS-1): delete this bridge when the hosted receipt producer lands.
    """
    if "schema_version" in wire or "subject" in wire or "status_url" in wire:
        return None
    run_id = wire.get("run_id")
    if run_id is not None and not isinstance(run_id, str):
        return None
    id_ = wire.get("id")
    item_id = id_ if isinstance(id_, str) and id_ else wire.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        return None
    if "status" not in wire:
        return (
            item_id
            if "run_id" in wire and run_id is None and item_id == wire.get("item_id")
            else None
        )
    return item_id if wire["status"] in _LEGACY_STORED_STATUS else None


def _legacy_receipt(wire: Mapping[str, Any], item_id: str) -> Receipt:
    global _legacy_warned
    if not _legacy_warned:
        _legacy_warned = True
        logger.warning(
            "legacy save shape read (no schema_version); treated as stored, with no run_id/status_url to await"
        )
    raw = _wrap(dict(wire))
    return Receipt(
        schema_version="legacy",
        subject=AttrDict({"kind": "item_save", "item_id": item_id}),
        run_id=None,
        status_url=None,
        processing_stage="stored",
        execution_state="running",  # stored, enrichment unknown: never "completed" beside terminal=False
        outcome=None,
        terminal=False,
        result_availability="none",
        raw=raw,
        legacy=True,
        legacy_status=wire.get("status")
        if isinstance(wire.get("status"), str)
        else None,
    )


def legacy_no_status() -> ReceiptError:
    """Typed refusal for an await/poll on a ``legacy`` receipt: there is no handle to follow.

    TODO(SVC-INGEST-WAIT-STATUS-1): remove with the bridge.
    """
    return ReceiptError(
        "legacy save receipt has no run_id/status_url to await or poll",
        code="legacy_receipt_no_status",
    )


def parse_receipt(wire: Any, *, legacy_bridge: bool = False) -> Receipt:
    """Decode one receipt body following ``x-reader-decoder``; raise ``ReceiptError`` for anything else.

    ``legacy_bridge`` (add and ingest saves only, TODO(SVC-INGEST-WAIT-STATUS-1)) also reads the pre-receipt
    add/ingest body as a stored ``legacy=True`` receipt. Off for edits, stages and status reads.
    """
    if not isinstance(wire, Mapping):
        raise _refuse(
            "not_a_receipt", f"expected a receipt object, got {type(wire).__name__}", {}
        )
    if "projection_kind" in wire:
        raise _refuse(
            "not_a_receipt",
            f"a {wire['projection_kind']} is a first-open projection, not a save receipt; it has no run to poll",
            wire,
        )
    version = wire.get("schema_version")
    if legacy_bridge and version is None:
        legacy_id = _legacy_item_id(wire)
        if legacy_id is not None:
            return _legacy_receipt(wire, legacy_id)
    if not isinstance(version, str):
        raise _refuse(
            "not_a_receipt",
            "body has no schema_version: this is not a 2.0 save receipt",
            wire,
        )
    try:
        major = int(version.split(".", 1)[0])
    except ValueError:
        raise _refuse(
            "malformed_receipt", f"unreadable schema_version {version!r}", wire
        ) from None
    if major != SUPPORTED_MAJOR:
        raise _refuse(
            "unsupported_version",
            f"receipt schema_version {version} is not major {SUPPORTED_MAJOR}",
            wire,
            schema_version=version,
        )
    subject = wire.get("subject")
    if not isinstance(subject, Mapping) or not isinstance(subject.get("kind"), str):
        raise _refuse("malformed_receipt", "receipt has no subject.kind", wire)
    if subject["kind"] not in SUBJECT_KINDS:
        raise _refuse(
            "unsupported_subject",
            f"unknown subject kind {subject['kind']!r}",
            wire,
            subject_kind=subject["kind"],
        )
    for name in ("run_id", "status_url"):
        if not isinstance(wire.get(name), str) or not wire[name]:
            raise _refuse("malformed_receipt", f"receipt has no {name}", wire)
    unknown = {
        name: wire[name]
        for name, allowed in (
            ("processing_stage", PROCESSING_STAGES),
            ("execution_state", EXECUTION_STATES),
            ("outcome", OUTCOMES),
            ("reason", REASONS),
            ("result_availability", RESULT_AVAILABILITY),
        )
        if wire.get(name) is not None and wire[name] not in allowed
    }
    if unknown:
        raise _refuse(
            "unsupported_state",
            f"unknown receipt state value(s) {unknown!r}",
            wire,
            **unknown,
        )
    if not isinstance(wire.get("terminal"), bool) or "result_availability" not in wire:
        raise _refuse(
            "malformed_receipt",
            "receipt has no terminal flag or result_availability",
            wire,
        )
    raw = _wrap(dict(wire))
    return Receipt(
        schema_version=version,
        subject=raw["subject"],
        run_id=wire["run_id"],
        status_url=wire["status_url"],
        processing_stage=wire.get("processing_stage"),
        execution_state=wire.get("execution_state"),
        outcome=wire.get("outcome"),
        terminal=wire["terminal"],
        result_availability=wire["result_availability"],
        client_timed_out=bool(wire.get("client_timed_out", False)),
        revision=wire.get("revision"),
        intake_id=wire.get("intake_id"),
        reason=wire.get("reason"),
        result=raw.get("result"),
        error=raw.get("error"),
        retry_after_ms=wire.get("retry_after_ms"),
        idempotency_key=wire.get("idempotency_key"),
        status_version=wire.get("status_version"),
        execution_epoch=wire.get("execution_epoch"),
        expected_revision=wire.get("expected_revision"),
        current_revision=wire.get("current_revision"),
        placement=wire.get("placement"),
        context=raw.get("context"),
        raw=raw,
    )


def timed_out(receipt: Receipt) -> Receipt:
    """The pending receipt an expired await returns: same handle, ``client_timed_out`` set, no server transition."""
    return replace(receipt, client_timed_out=True)
