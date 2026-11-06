"""Shared assertions for the frozen 2.0 item-save receipt contract."""

from smartmemory_client.receipt import Receipt


def assert_item_receipt(receipt):
    """Require a real admitted save and return its item handle for CRUD calls."""
    assert isinstance(receipt, Receipt)
    assert receipt.schema_version.split(".")[0] == "1"
    assert receipt.legacy is False
    assert receipt.subject_kind == "item_save"
    assert isinstance(receipt.item_id, str) and receipt.item_id
    assert isinstance(receipt.run_id, str) and receipt.run_id
    assert receipt.status_url == f"/memory/status/{receipt.run_id}"
    assert receipt.processing_stage in {"stored", "extracted"}
    assert receipt.terminal is True
    assert receipt.execution_state == "completed"
    assert receipt.outcome in {"completed", "skipped", "no_op"}
    assert receipt.client_timed_out is False
    assert receipt.revision is not None
    return receipt.item_id
