"""Optional origin context survives Python SDK request serialization."""

from unittest.mock import MagicMock

from smartmemory_client.client import SmartMemoryClient


def test_ingest_and_conversation_context():
    client = SmartMemoryClient.__new__(SmartMemoryClient)
    client._request = MagicMock(return_value={})
    context = {"origin": "import:obsidian"}
    client.ingest("note", context=context)
    assert client._request.call_args.kwargs["json_body"]["context"] == context
    client.ingest_conversation([{"role": "user", "content": "hello"}], context=context)
    assert client._request.call_args.kwargs["json_body"]["context"] == context
