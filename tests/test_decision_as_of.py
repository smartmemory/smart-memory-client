"""SM-ASOF-DECISIONS-1: ``as_of`` on the dated decision reads, policy bundle and recall pack.

Request-shape tests: ``as_of`` travels as the ``as_of`` query param (GETs) or body key
(recall pack) only when set, so a call without it sends exactly the request it sent
before. The server owns the as-of semantics and the 400 ``invalid_as_of``.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import (
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)
from smartmemory_client.client import SmartMemoryClient

T = "2026-01-02T03:04:05Z"


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


def _ok(body):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _err(status, text):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {}
    resp.text = text
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=resp
    )
    return resp


# (method, args, http verb, path) for every dated GET read.
DATED_GETS = [
    ("get_decision", ("dec_1",), "GET", "/memory/decisions/dec_1"),
    ("list_decisions", (), "GET", "/memory/decisions"),
    ("search_decisions", ("auth",), "GET", "/memory/decisions/search"),
    ("get_provenance_chain", ("dec_1",), "GET", "/memory/decisions/dec_1/provenance"),
    ("policy_bundle", (), "GET", "/memory/policy/bundle"),
]


@pytest.mark.parametrize("method,args,verb,path", DATED_GETS)
@patch("httpx.Client.request")
def test_as_of_sent_as_query_param(mock_req, client, method, args, verb, path):
    mock_req.return_value = _ok({"decisions": [], "as_of": T})

    getattr(client, method)(*args, as_of=T)

    assert mock_req.call_args[0][0] == verb
    assert mock_req.call_args[0][1].endswith(path)
    assert mock_req.call_args.kwargs["params"]["as_of"] == T


@pytest.mark.parametrize("method,args,verb,path", DATED_GETS)
@patch("httpx.Client.request")
def test_no_as_of_sends_no_param(mock_req, client, method, args, verb, path):
    mock_req.return_value = _ok({"decisions": []})

    getattr(client, method)(*args)

    params = mock_req.call_args.kwargs.get("params") or {}
    assert "as_of" not in params


@patch("httpx.Client.request")
def test_get_and_provenance_without_as_of_send_no_params(mock_req, client):
    """The undated get and provenance calls stay byte-identical: no params at all."""
    mock_req.return_value = _ok({})

    client.get_decision("dec_1")
    assert mock_req.call_args.kwargs.get("params") is None
    client.get_provenance_chain("dec_1")
    assert mock_req.call_args.kwargs.get("params") is None


@patch("httpx.Client.request")
def test_list_as_of_keeps_other_filters(mock_req, client):
    mock_req.return_value = _ok({"decisions": [{"decision_id": "dec_1"}], "as_of": T})

    result = client.list_decisions(domain="backend", limit=5, as_of=T)

    assert result == [{"decision_id": "dec_1"}]
    params = mock_req.call_args.kwargs["params"]
    assert params == {
        "min_confidence": 0.0,
        "limit": 5,
        "domain": "backend",
        "as_of": T,
    }


@patch("httpx.Client.request")
def test_policy_bundle_as_of_keeps_status_list(mock_req, client):
    mock_req.return_value = _ok({"rules": [], "as_of": T})

    bundle = client.policy_bundle(workflow="deploy", as_of=T)

    assert bundle["as_of"] == T
    params = mock_req.call_args.kwargs["params"]
    assert params == {"status": ["active"], "workflow": "deploy", "as_of": T}


@patch("httpx.Client.request")
def test_recall_pack_as_of_in_body(mock_req, client):
    mock_req.return_value = _ok(
        {"block": "", "manifest": {"as_of": T, "dropped_sections": ["active_plan"]}}
    )

    pack = client.recall_pack(4000, query="auth", as_of=T)

    assert pack["manifest"]["dropped_sections"] == ["active_plan"]
    assert mock_req.call_args[0][1].endswith("/memory/recall/pack")
    assert mock_req.call_args.kwargs["json"] == {
        "budget_tokens": 4000,
        "query": "auth",
        "as_of": T,
    }


@patch("httpx.Client.request")
def test_recall_pack_without_as_of_has_no_key(mock_req, client):
    mock_req.return_value = _ok({"block": "", "manifest": {}})

    client.recall_pack(4000)

    assert mock_req.call_args.kwargs["json"] == {"budget_tokens": 4000}


class TestErrors:
    @patch("httpx.Client.request")
    def test_invalid_as_of_is_validation_error(self, mock_req, client):
        mock_req.return_value = _err(
            400, '{"detail":{"code":"invalid_as_of","message":"not-a-date"}}'
        )
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.list_decisions(as_of="not-a-date")
        assert exc.value.status_code == 400

    @patch("httpx.Client.request")
    def test_unknown_decision_as_of_is_not_found(self, mock_req, client):
        mock_req.return_value = _err(404, "Decision not found")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.get_decision("dec_missing", as_of=T)
        assert exc.value.status_code == 404

    @patch("httpx.Client.request")
    def test_server_error_as_of(self, mock_req, client):
        mock_req.return_value = _err(500, "boom")
        with pytest.raises(SmartMemoryServerError) as exc:
            client.policy_bundle(as_of=T)
        assert exc.value.status_code == 500
