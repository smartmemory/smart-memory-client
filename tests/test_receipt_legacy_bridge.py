"""Legacy add/ingest save body bridge (PYCLIENT-2.0-RECEIPT-LEGACY-BRIDGE-1), plain dicts, no server.

TODO(SVC-INGEST-WAIT-STATUS-1): delete with the bridge when the hosted receipt producer lands.
"""

import logging

import pytest

from smartmemory_client import _save_transport as transport
from smartmemory_client import receipt as receipt_mod
from smartmemory_client.errors import ReceiptError
from smartmemory_client.receipt import parse_receipt

V1 = {
    "schema_version": "1.1",
    "subject": {"kind": "item_save", "item_id": "i1"},
    "run_id": "r1",
    "status_url": "/memory/status/r1",
    "processing_stage": "received",
    "execution_state": "queued",
    "terminal": False,
    "result_availability": "pending",
}

# (name, bridge, body, expected): expected is ("receipt", item_id, legacy) or ("refused", code)
ROWS = [
    ("1.x receipt unchanged", True, V1, ("receipt", "i1", False)),
    ("1.x receipt unchanged, bridge off", False, V1, ("receipt", "i1", False)),
    (
        "add created",
        True,
        {"id": "a1", "status": "created", "pipeline_used": "x"},
        ("receipt", "a1", True),
    ),
    (
        "add unchanged",
        True,
        {"id": "a2", "status": "unchanged"},
        ("receipt", "a2", True),
    ),
    ("add replaced", True, {"id": "a3", "status": "replaced"}, ("receipt", "a3", True)),
    (
        "ingest item_id",
        True,
        {"item_id": "n1", "status": "created", "run_id": None},
        ("receipt", "n1", True),
    ),
    (
        "ingest dedupe no status",
        True,
        {"item_id": "n2", "run_id": None},
        ("receipt", "n2", True),
    ),
    (
        "legacy body, bridge off",
        False,
        {"id": "a1", "status": "created"},
        ("refused", "not_a_receipt"),
    ),
    ("random dict", True, {"hello": "world"}, ("refused", "not_a_receipt")),
    ("missing id", True, {"status": "created"}, ("refused", "not_a_receipt")),
    ("empty id", True, {"id": "", "status": "created"}, ("refused", "not_a_receipt")),
    (
        "non-string id",
        True,
        {"id": 7, "status": "created"},
        ("refused", "not_a_receipt"),
    ),
    (
        "unknown status",
        True,
        {"id": "a1", "status": "held"},
        ("refused", "not_a_receipt"),
    ),
    ("id without status", True, {"id": "a1"}, ("refused", "not_a_receipt")),
    (
        "status_url present",
        True,
        {"id": "a1", "status": "created", "status_url": "/s"},
        ("refused", "not_a_receipt"),
    ),
    (
        "non-string run_id",
        True,
        {"id": "a1", "status": "created", "run_id": 5},
        ("refused", "not_a_receipt"),
    ),
    (
        "unsupported major",
        True,
        {**V1, "schema_version": "2.0"},
        ("refused", "unsupported_version"),
    ),
]


@pytest.mark.parametrize("name,bridge,body,expected", ROWS, ids=[r[0] for r in ROWS])
def test_rows(name, bridge, body, expected):
    if expected[0] == "refused":
        with pytest.raises(ReceiptError) as info:
            parse_receipt(body, legacy_bridge=bridge)
        assert info.value.code == expected[1]
        return
    got = parse_receipt(body, legacy_bridge=bridge)
    assert (got.item_id, got.legacy) == (expected[1], expected[2])
    if got.legacy:
        assert (got.run_id, got.status_url, got.processing_stage, got.terminal) == (
            None,
            None,
            "stored",
            False,
        )
        assert got.legacy_status == body.get("status")


def test_legacy_await_refused_before_any_read():
    got = parse_receipt({"id": "a1", "status": "created"}, legacy_bridge=True)
    reads = []
    with pytest.raises(ReceiptError) as info:
        transport.await_receipt(
            lambda path, params: reads.append(path), got, target="stored"
        )
    assert info.value.code == "legacy_receipt_no_status" and reads == []
    with pytest.raises(ReceiptError) as info:
        transport.status_path(got)
    assert info.value.code == "legacy_receipt_no_status"


def test_warns_once_per_process_without_values(monkeypatch, caplog):
    monkeypatch.setattr(receipt_mod, "_legacy_warned", False)
    with caplog.at_level(logging.WARNING, logger=receipt_mod.logger.name):
        for ident in ("secret-id-1", "secret-id-2"):
            parse_receipt({"id": ident, "status": "created"}, legacy_bridge=True)
    lines = [
        r.getMessage() for r in caplog.records if "legacy save shape" in r.getMessage()
    ]
    assert len(lines) == 1 and "secret-id" not in lines[0]
