"""Prepared explicit public waits for save-then-read suites (U49.A2, C-49.contract.sdk-suites; G11, G12, G47).

A test that saves through a public seam and then reads names what it waits for: the ``stored`` or ``extracted``
milestone, or the ``terminal`` outcome, within ``deadline_s`` seconds. ``await_public(observe, wait=, deadline_s=)``
polls ``observe`` (a zero-argument read through the public seam) and answers with a ``PublicWaitResult`` whose
``outcome`` is one of ``OUTCOMES``:

- ``reached``: the milestone holds. ``unreached``: the run completed without it.
- ``client_timed_out``: still pending at the deadline (the result carries attempts, elapsed seconds and the last
  observation; nothing is cancelled).
- ``failed``/``skipped``/``dead``/``partial``: the run's explicit fault, returned on the first read that shows it.
  A fault is never retried, so no poll loop can hide it.
- ``refused``: the run is held (paused), reported with one WARNING.

A read that cannot be answered (the seam raised, returned an unreadable observation, a bad argument, or the seam
carries no status for the requested milestone) is the typed ``PublicWaitRefused`` with exactly one WARNING. It is
never read as "absent" or as a timeout.

This mirrors the vocabulary of core's local wait helper (core's own testing package) and deliberately does not import it:
outer-repo suites must not (core ``tests/contract/test_no_hidden_sync_pin.py``). No new SDK API is added: the
adapters below read through ``SmartMemoryClient.get`` and ``search`` only.

SDK gap, owned by C-01.activate.save.hosted-adapters (ring 3): ``MemoryItem`` carries no ``read_status``, so the SDK
can observe the ``stored`` milestone only. ``wait="extracted"`` and ``wait="terminal"`` are refused by name, never
polled to a timeout, until the SDK gains the carrier (``test_public_wait.py`` pins the gap and fails when it closes).
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

# --- CORE BEGIN (byte-identical in smart-memory-client and smart-memory-mcp tests/public_wait.py) ---
logger = logging.getLogger("public_wait")

WAITS: tuple[str, ...] = ("stored", "extracted", "terminal")
OUTCOMES: tuple[str, ...] = (
    "reached",
    "client_timed_out",
    "failed",
    "skipped",
    "dead",
    "partial",
    "unreached",
    "refused",
)
FAULTS: tuple[str, ...] = ("failed", "skipped", "dead", "partial")
_STAGES = {
    "stored": ("stored", "extracted"),
    "extracted": ("extracted",),
    "terminal": (),
}
POLL_S = 0.05
MAX_POLL_S = 0.5


class PublicWaitRefused(RuntimeError):
    """The wait could not be answered. Always logged once, where it is raised."""


class PublicWaitArgumentError(PublicWaitRefused, ValueError):
    """A caller argument no wait could honour; refused before any read."""


@dataclass(frozen=True)
class Observation:
    """One read through a public seam. ``stage`` None: not readable yet (queued). ``status_carried`` False: the seam
    cannot say anything about extraction or the terminal outcome, so only ``stored`` is answerable."""

    stage: str | None = None
    terminal: bool = False
    outcome: str | None = None
    held: str | None = None
    status_carried: bool = True
    detail: str = ""


@dataclass(frozen=True)
class PublicWaitResult:
    outcome: str
    wait: str
    attempts: int
    elapsed_s: float
    last: Observation | None
    reason: str = ""


def refuse(
    reason: str, error: type[PublicWaitRefused] = PublicWaitRefused, *, log: bool = True
) -> PublicWaitRefused:
    """The typed refusal with its one WARNING. Adapters raise what this returns; ``await_public`` never logs it again.

    ``log=False`` only when the product already logged this exact refusal once (a typed error it raised); the
    refusal still carries the reason, and the caller's test pins that exactly one WARNING exists.
    """
    if log:
        logger.warning("Explicit public wait refused: %s", reason)
    return error(reason)


def describe(error: BaseException) -> str:
    """``Type: message`` for a refusal reason. Formatting a message can itself raise, so it is guarded."""
    try:
        text = str(error)
    except Exception:  # noqa: BLE001 - a diagnostic never stops the refusal from being raised
        text = "<unprintable>"
    return f"{type(error).__name__}: {text[:200]}"


def _finite(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def shown(value: object) -> str:
    try:
        return (
            repr(value)[:48]
            if type(value) in (str, int, float, bool, type(None))
            else type(value).__name__
        )
    except Exception:  # noqa: BLE001 - a diagnostic never stops the refusal
        return "<unprintable>"


def _check(observe: object, wait: object, deadline_s: object, poll_s: object) -> None:
    if not callable(observe):
        raise refuse(
            f"observe must be callable, got {shown(observe)}", PublicWaitArgumentError
        )
    if type(wait) is not str or wait not in WAITS:
        raise refuse(
            f"wait must be one of {WAITS}, got {shown(wait)}", PublicWaitArgumentError
        )
    if not _finite(deadline_s) or deadline_s < 0:
        raise refuse(
            f"deadline_s must be a finite number >= 0, got {shown(deadline_s)}",
            PublicWaitArgumentError,
        )
    if not _finite(poll_s) or poll_s <= 0:
        raise refuse(
            f"poll_s must be a positive finite number, got {shown(poll_s)}",
            PublicWaitArgumentError,
        )


def _decide(obs: Observation, wait: str) -> tuple[str | None, str]:
    """The outcome one observation already decides (None: pending) and its reason."""
    if type(obs) is not Observation:
        raise refuse(f"the read returned {type(obs).__name__}, not an Observation")
    if obs.held is not None:
        logger.warning(
            "Explicit public wait: the run is held (%s); reported refused, not polled further",
            shown(obs.held),
        )
        return "refused", f"held: {obs.held}"
    if wait != "stored" and not obs.status_carried:
        raise refuse(
            f"this public seam carries no extraction or terminal status, so wait={wait!r} is unobservable "
            f"(only 'stored' is); last read: {obs.detail or 'none'}"
        )
    if obs.terminal:
        if obs.outcome in FAULTS:
            return obs.outcome, f"terminal outcome {obs.outcome}"
        if obs.outcome not in ("completed", "no_op"):
            raise refuse(f"a terminal observation carries outcome {shown(obs.outcome)}")
        if wait == "terminal" or obs.stage in _STAGES[wait]:
            return "reached", obs.detail
        return (
            "unreached",
            f"completed at stage {shown(obs.stage)} without reaching {wait}",
        )
    if obs.stage in _STAGES[wait]:
        return "reached", obs.detail
    return None, obs.detail


def await_public(
    observe: Callable[[], Observation],
    *,
    wait: str,
    deadline_s: float,
    poll_s: float = POLL_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PublicWaitResult:
    """Wait until ``observe()`` shows ``wait`` or the explicit fault, for at most ``deadline_s`` seconds.

    ``deadline_s`` 0 reads once. A read that raises is not retried: it is the typed refusal with one WARNING
    (a ``PublicWaitRefused`` an adapter raised already logged itself and is re-raised as is).
    """
    _check(observe, wait, deadline_s, poll_s)
    start = clock()
    delay = poll_s
    attempts = 0
    while True:
        attempts += 1
        try:
            obs = observe()
        except PublicWaitRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - an unreadable seam is a typed refusal, never "still pending"
            raise refuse(
                f"the read through the public seam failed ({describe(exc)})"
            ) from exc
        outcome, reason = _decide(obs, wait)
        if outcome is not None:
            return PublicWaitResult(
                outcome, wait, attempts, clock() - start, obs, reason
            )
        remaining = deadline_s - (clock() - start)
        if remaining <= 0:
            return PublicWaitResult(
                "client_timed_out", wait, attempts, clock() - start, obs, obs.detail
            )
        sleep(min(delay, remaining))
        delay = min(delay * 2, MAX_POLL_S)


# --- CORE END ---


def observe_get(client, item_id: str) -> Callable[[], Observation]:
    """Read ``item_id`` through ``SmartMemoryClient.get``. A readable item is the ``stored`` milestone.

    A 404 (``SmartMemoryNotFoundError``) means not readable yet: queued, visible as ``client_timed_out`` at the
    deadline. Any other SDK error (auth, 5xx, validation, transport) is a refusal, never read as absence. The SDK
    carries no status, so every observation says so and only ``wait="stored"`` is answerable.
    """
    from smartmemory_client import SmartMemoryClientError, SmartMemoryNotFoundError

    def observe() -> Observation:
        try:
            item = client.get(item_id)
        except SmartMemoryNotFoundError:
            return Observation(
                status_carried=False,
                detail=f"get({shown(item_id)}) answered 404, not readable yet",
            )
        except SmartMemoryClientError as exc:
            raise refuse(f"get({shown(item_id)}) failed ({describe(exc)})") from exc
        if item is None:
            return Observation(
                status_carried=False,
                detail=f"get({shown(item_id)}) returned None, not readable yet",
            )
        return Observation(
            stage="stored",
            status_carried=False,
            detail=f"get({shown(item_id)}) returned the item",
        )

    return observe


def observe_search(
    client, query: str, item_id: str, **search_kwargs
) -> Callable[[], Observation]:
    """Read through ``SmartMemoryClient.search``: the item appearing in the results is the ``stored`` milestone."""
    from smartmemory_client import SmartMemoryClientError

    def observe() -> Observation:
        try:
            found = client.search(query, **search_kwargs)
        except SmartMemoryClientError as exc:
            raise refuse(f"search({shown(query)}) failed ({describe(exc)})") from exc
        if type(found) is not list:
            raise refuse(
                f"search({shown(query)}) returned {type(found).__name__}, not a list"
            )
        if any(getattr(row, "item_id", None) == item_id for row in found):
            return Observation(
                stage="stored",
                status_carried=False,
                detail=f"search({shown(query)}) listed {shown(item_id)}",
            )
        return Observation(
            status_carried=False,
            detail=f"search({shown(query)}) did not list {shown(item_id)} ({len(found)} rows)",
        )

    return observe
