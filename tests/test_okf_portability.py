"""Unit tests for OKF bundle portability client methods."""

from unittest.mock import MagicMock, patch

from smartmemory_client import SmartMemoryClient


BASE_URL = "http://localhost:9001"
ARCHIVE = b"\x1f\x8bOKF bundle bytes"


def _client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url=BASE_URL,
        token="test-token",
        workspace_id="workspace-1",
    )


def _response(*, content: bytes = b"", payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.content = content
    response.json.return_value = payload or {}
    response.raise_for_status.return_value = None
    return response


@patch("httpx.Client.request")
def test_export_okf_returns_archive_bytes_with_workspace_auth(mock_request):
    mock_request.return_value = _response(content=ARCHIVE)

    client = _client()
    try:
        assert client.export_okf() == ARCHIVE

        method, url = mock_request.call_args.args
        assert method == "GET"
        assert url == f"{BASE_URL}/memory/okf/export"
        assert mock_request.call_args.kwargs["headers"] == {
            "Authorization": "Bearer test-token",
            "X-Workspace-Id": "workspace-1",
        }
    finally:
        client.close()


@patch("httpx.Client.request")
def test_import_okf_uploads_archive_as_multipart_with_workspace_auth(mock_request):
    result = {"imported": 3, "failed": 1, "workspace_id": "workspace-1"}
    mock_request.return_value = _response(payload=result)

    client = _client()
    try:
        assert client.import_okf(ARCHIVE) == result

        method, url = mock_request.call_args.args
        assert method == "POST"
        assert url == f"{BASE_URL}/memory/okf/import"
        assert mock_request.call_args.kwargs["headers"] == {
            "Authorization": "Bearer test-token",
            "X-Workspace-Id": "workspace-1",
        }
        assert mock_request.call_args.kwargs["files"] == {
            "file": (
                "smartmemory-okf-import.tar.gz",
                ARCHIVE,
                "application/gzip",
            )
        }
    finally:
        client.close()


@patch("httpx.Client.request")
def test_export_okf_without_vectors_sends_the_flag(mock_request):
    """BUG-OKF-IMPORT-SLOW-1: vectors=False asks for the smaller file; the default sends no flag."""
    mock_request.return_value = _response(content=ARCHIVE)

    client = _client()
    try:
        client.export_okf(vectors=False)
        assert mock_request.call_args.kwargs["params"] == {"vectors": "false"}
        client.export_okf()
        assert mock_request.call_args.kwargs["params"] is None
    finally:
        client.close()


@patch("httpx.Client.request")
def test_background_import_and_job_status(mock_request):
    """BUG-OKF-IMPORT-SLOW-1: background=True sends the flag; okf_import_job reads the run."""
    started = {
        "run_id": "okf-import-1",
        "status": "queued",
        "total": 240,
        "deadline_at": 1.0,
    }
    mock_request.return_value = _response(payload=started)

    client = _client()
    try:
        assert client.import_okf(ARCHIVE, background=True) == started
        assert mock_request.call_args.kwargs["params"] == {"background": "true"}

        state = {
            "run_id": "okf-import-1",
            "status": "completed",
            "done": 240,
            "total": 240,
            "result": {},
        }
        mock_request.return_value = _response(payload=state)
        assert client.okf_import_job("okf-import-1") == state
        method, url = mock_request.call_args.args
        assert (method, url) == ("GET", f"{BASE_URL}/memory/okf/jobs/okf-import-1")
    finally:
        client.close()
