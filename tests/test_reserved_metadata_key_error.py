"""A save refused for a reserved metadata key raises ``ReservedMetadataKeyError`` (SVC-2.0-METADATA-RESERVED-KEY-REFUSE-1).

The service answers 400 with ``detail: {"error_type": "reserved_metadata_key", "key", "message"}`` (contract
``smart-memory-docs/docs/features/PLAT-API-CODES-1/api-codes-contract.json``). One row table: each row is a save call and
the server's answer, and the exception class (and key) the caller gets. HTTP is mocked, no server.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import ReservedMetadataKeyError, SmartMemoryClient
from smartmemory_client.client import (
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE_URL = "http://localhost:9001"


def _response(status_code, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = {}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"{status_code} Error",
        request=MagicMock(spec=httpx.Request),
        response=resp,
    )
    if json_data is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data
    return resp


def _reserved(key):
    return {
        "detail": {
            "error_type": "reserved_metadata_key",
            "key": key,
            "message": f"metadata key '{key}' is reserved: the server sets it from your credentials.",
        }
    }


def _add(client):
    client.add("c", metadata={"workspace_id": "other"})


def _ingest(client):
    client.ingest("c", context={"scope": "x"})


def _raw(client):
    client._request("POST", "/memory/ingest/conversation", json_body={"turns": []})


# row id | call | status | JSON body (None = not JSON) | expected class | expected key
ROWS = [
    (
        "add-reserved",
        _add,
        400,
        _reserved("workspace_id"),
        ReservedMetadataKeyError,
        "workspace_id",
    ),
    (
        "ingest-reserved",
        _ingest,
        400,
        _reserved("scope"),
        ReservedMetadataKeyError,
        "scope",
    ),
    (
        "request-reserved",
        _raw,
        400,
        _reserved("owner_key"),
        ReservedMetadataKeyError,
        "owner_key",
    ),
    (
        "other-400-string-detail",
        _add,
        400,
        {"detail": "Invalid memory_type"},
        SmartMemoryValidationError,
        None,
    ),
    (
        "other-400-error-type",
        _add,
        400,
        {"detail": {"error_type": "scope_required"}},
        SmartMemoryValidationError,
        None,
    ),
    ("400-not-json", _add, 400, None, SmartMemoryValidationError, None),
    (
        "422-same-body-not-mapped",
        _add,
        422,
        _reserved("scope"),
        SmartMemoryValidationError,
        None,
    ),
    ("500", _add, 500, {"detail": "boom"}, SmartMemoryServerError, None),
]


@pytest.mark.parametrize(
    "call,status,body,expected,key", [pytest.param(*r[1:], id=r[0]) for r in ROWS]
)
@patch("httpx.Client.request")
def test_reserved_metadata_key_error(mock_request, call, status, body, expected, key):
    mock_request.return_value = _response(status, body, text=str(body))
    client = SmartMemoryClient(base_url=BASE_URL, api_key="sk_test_reserved")
    with pytest.raises(expected) as raised:
        call(client)
    assert type(raised.value) is expected
    assert raised.value.status_code == status
    if expected is ReservedMetadataKeyError:
        assert raised.value.key == key
        # Still the 400 class every existing handler catches.
        assert isinstance(raised.value, SmartMemoryValidationError)
    if status < 500:
        assert mock_request.call_count == 1, "a 4xx is never retried"
