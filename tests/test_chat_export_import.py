"""Python SDK coverage for the chat-export importer (DIST-CHAT-IMPORT-1)."""

import json
from unittest.mock import patch

import httpx

from smartmemory_client.client import SmartMemoryClient

BASE_URL = "https://api.example.test"
JSON_EXPORT = json.dumps([{"uuid": "c1", "chat_messages": []}]).encode()
ZIP_EXPORT = b"PK\x03\x04rest-of-a-zip"


def _response(payload):
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", f"{BASE_URL}/memory/import/chat-export"),
    )


def _client():
    return SmartMemoryClient(
        base_url=BASE_URL, api_key="test-token", workspace_id="workspace-1"
    )


@patch("httpx.Client.request")
def test_import_chat_export_posts_multipart_with_form_fields(mock_request):
    result = {
        "source_format": "claude",
        "conversations_imported": 2,
        "conversations_failed": 0,
        "turns_imported": 9,
        "items_created": 2,
        "warnings": [],
    }
    mock_request.return_value = _response(result)

    client = _client()
    try:
        assert (
            client.import_chat_export(
                JSON_EXPORT, source_format="claude", max_conversations=5
            )
            == result
        )

        method, url = mock_request.call_args.args
        assert method == "POST"
        assert url == f"{BASE_URL}/memory/import/chat-export"
        assert mock_request.call_args.kwargs["files"] == {
            "file": ("conversations.json", JSON_EXPORT, "application/json")
        }
        assert mock_request.call_args.kwargs["data"] == {
            "source_format": "claude",
            "max_conversations": "5",
        }
    finally:
        client.close()


@patch("httpx.Client.request")
def test_zip_payload_is_sent_with_a_zip_content_type(mock_request):
    """The magic-byte sniff must not mislabel a vendor archive as JSON."""
    mock_request.return_value = _response({"source_format": "chatgpt", "warnings": []})

    client = _client()
    try:
        client.import_chat_export(ZIP_EXPORT, filename="export.zip")
        assert mock_request.call_args.kwargs["files"]["file"][2] == "application/zip"
    finally:
        client.close()


@patch("httpx.Client.request")
def test_defaults_are_auto_detection_and_a_25_conversation_cap(mock_request):
    mock_request.return_value = _response({"source_format": "claude", "warnings": []})

    client = _client()
    try:
        client.import_chat_export(JSON_EXPORT)
        assert mock_request.call_args.kwargs["data"] == {
            "source_format": "auto",
            "max_conversations": "25",
        }
    finally:
        client.close()


@patch("httpx.Client.request")
def test_warnings_survive_to_the_caller(mock_request):
    """A capped import must not look identical to a complete one."""
    mock_request.return_value = _response(
        {
            "source_format": "claude",
            "conversations_imported": 25,
            "conversations_failed": 0,
            "turns_imported": 400,
            "items_created": 30,
            "warnings": [
                "112 conversation(s) not imported: the request capped ingestion at 25."
            ],
        }
    )

    client = _client()
    try:
        assert "not imported" in client.import_chat_export(JSON_EXPORT)["warnings"][0]
    finally:
        client.close()


@patch("httpx.Client.request")
def test_chat_export_formats_hits_the_formats_endpoint(mock_request):
    mock_request.return_value = httpx.Response(
        200,
        json={"formats": [{"id": "chatgpt"}, {"id": "claude"}]},
        request=httpx.Request("GET", f"{BASE_URL}/memory/import/chat-export/formats"),
    )

    client = _client()
    try:
        assert {f["id"] for f in client.chat_export_formats()["formats"]} == {
            "chatgpt",
            "claude",
        }
        method, url = mock_request.call_args.args
        assert method == "GET"
        assert url == f"{BASE_URL}/memory/import/chat-export/formats"
    finally:
        client.close()
