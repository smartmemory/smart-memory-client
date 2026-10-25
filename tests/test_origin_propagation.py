"""Optional origin context survives Python SDK request serialization."""

from unittest.mock import MagicMock

from smartmemory_client.client import SmartMemoryClient


SAVE_RECEIPT = {
    "schema_version": "1.1",
    "subject": {"kind": "item_save", "item_id": "m-1"},
    "run_id": "run_1",
    "status_url": "/memory/status/run_1",
    "processing_stage": "received",
    "execution_state": "queued",
    "outcome": None,
    "terminal": False,
    "result_availability": "pending",
    "client_timed_out": False,
}


def test_ingest_and_conversation_context():
    client = SmartMemoryClient.__new__(SmartMemoryClient)
    client._request = MagicMock(return_value=SAVE_RECEIPT)
    context = {"origin": "import:obsidian"}
    client.ingest("note", context=context)
    assert client._request.call_args.kwargs["json_body"]["context"] == context
    client.ingest_conversation([{"role": "user", "content": "hello"}], context=context)
    assert client._request.call_args.kwargs["json_body"]["context"] == context
