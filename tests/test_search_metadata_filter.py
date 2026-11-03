"""DEV-ONBOARD-FU-SCOPED-SEARCH-1: search(metadata_filter=...) request shape and errors."""

from unittest.mock import Mock, patch

import httpx
import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client import SmartMemoryValidationError


def _client():
    return SmartMemoryClient(base_url="http://test", team_id="ws", api_key="fake")


def _ok(coverage=None):
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"results": [], "coverage": coverage or {}}
    return response


@pytest.mark.parametrize(
    "flt, sent",
    [
        (None, None),
        ({}, None),
        ({"customer_id": "cus_8812"}, {"customer_id": "cus_8812"}),
        (
            {"priority": {"gte": 2}, "customer_id": "c"},
            {"priority": {"gte": 2}, "customer_id": "c"},
        ),
    ],
    ids=["absent", "empty", "equality", "operator"],
)
def test_metadata_filter_body(flt, sent):
    client = _client()
    with patch("httpx.Client.request", return_value=_ok()) as request:
        client.search("billing plan", metadata_filter=flt)
    body = request.call_args.kwargs["json"]
    assert body.get("metadata_filter") == sent
    assert ("metadata_filter" in body) is (sent is not None)


def test_non_dict_filter_is_refused_before_any_request():
    client = _client()
    with (
        patch("httpx.Client.request") as request,
        pytest.raises(ValueError, match="must be a dict"),
    ):
        client.search("x", metadata_filter=[("customer_id", "c")])
    assert not request.called


def test_incomplete_coverage_is_exposed():
    client = _client()
    with patch(
        "httpx.Client.request", return_value=_ok({"metadata_filter_incomplete": True})
    ):
        client.search("x", metadata_filter={"customer_id": "c"})
    assert client.last_search_coverage == {"metadata_filter_incomplete": True}


def test_scope_key_refusal_surfaces_as_typed_error():
    client = _client()
    request = httpx.Request("POST", "http://test/memory/search")
    response = httpx.Response(
        422,
        request=request,
        json={
            "detail": {
                "error": "invalid_metadata_filter",
                "message": "names a scope boundary",
            }
        },
    )
    with patch("httpx.Client.request", return_value=response):
        with pytest.raises(SmartMemoryValidationError) as info:
            client.search("x", metadata_filter={"workspace_id": "other"})
    assert info.value.status_code == 422
    assert "invalid_metadata_filter" in str(info.value)
