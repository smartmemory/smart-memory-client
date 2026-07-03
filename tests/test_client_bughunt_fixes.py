"""Regression tests for QUALITY-BUGHUNT-1 client-py findings.

Each test asserts the *mechanism* of a fix, not just an echo:

- link() no longer swallows transport/HTTP errors into a silent ``return False``;
  it lets _request's typed exceptions propagate (silent-degradation finding,
  client.py:1039).
- search() raises a typed subclass carrying status_code/detail like every other
  method, instead of a bare SmartMemoryClientError (contract-violation finding,
  client.py:569).
- summary_latest/summary_get/summary_delta detect not-found via
  ``isinstance(e, SmartMemoryNotFoundError)`` rather than the fragile
  ``"404" in str(e)`` substring — so a NON-404 error whose body merely contains
  the digits "404" is NOT misclassified as not-found (correctness finding,
  client.py:3407).
- search() forwards the documented server params decompose / semantic_hops /
  include_reference into the request body (contract-violation finding,
  client.py:459).

All HTTP calls are mocked (``httpx.request``) — no running server required,
mirroring tests/test_client_errors.py and tests/test_summary_client.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

BASE_URL = "http://localhost:9001"
API_KEY = "test_token_abc"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(base_url=BASE_URL, api_key=API_KEY)


def _build_response(
    status_code: int, body: str = "", json_data: dict | list | None = None
) -> MagicMock:
    """Mock httpx.Response that raises HTTPStatusError (with status_code) on >=400.

    Identical shape to the helpers in test_client_errors.py / test_summary_client.py
    so _request maps the status to the right typed exception.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    resp.headers = {}
    if status_code >= 400:
        request = MagicMock(spec=httpx.Request)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code} Error",
            request=request,
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


# ---------------------------------------------------------------------------
# link() — no longer swallows errors into silent False
# ---------------------------------------------------------------------------


class TestLinkPropagatesErrors:
    @patch("httpx.Client.request")
    def test_link_success_returns_true_and_posts_body(self, mock_req, client):
        mock_req.return_value = _build_response(200, json_data={"linked": True})
        assert client.link("src", "tgt", link_type="CAUSES") is True
        # Mechanism: the POST body carries the link payload.
        call = mock_req.call_args
        assert call.args[0] == "POST"
        assert "/memory/link" in call.args[1]
        body = call.kwargs["json"]
        assert body == {
            "source_id": "src",
            "target_id": "tgt",
            "link_type": "CAUSES",
        }

    @patch("httpx.Client.request")
    def test_link_404_raises_not_found_not_false(self, mock_req, client):
        # Old behavior collapsed this to ``return False``; now it must raise.
        mock_req.return_value = _build_response(404, body="source not found")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.link("missing_src", "tgt")
        assert exc.value.status_code == 404

    @patch("httpx.Client.request")
    def test_link_403_raises_permission_not_false(self, mock_req, client):
        mock_req.return_value = _build_response(403, body="forbidden")
        with pytest.raises(SmartMemoryPermissionError) as exc:
            client.link("src", "tgt")
        assert exc.value.status_code == 403

    @patch("httpx.Client.request")
    def test_link_500_raises_server_not_false(self, mock_req, client):
        mock_req.return_value = _build_response(500, body="link write failed")
        with pytest.raises(SmartMemoryServerError) as exc:
            client.link("src", "tgt")
        assert exc.value.status_code == 500

    @patch("httpx.Client.request")
    def test_link_transport_error_raises_not_false(self, mock_req, client):
        # A network failure must surface, not be swallowed into False.
        mock_req.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(SmartMemoryClientError):
            client.link("src", "tgt")


# ---------------------------------------------------------------------------
# search() — raises typed subclass with status_code/detail (not bare base)
# ---------------------------------------------------------------------------


class TestSearchTypedErrors:
    @patch("httpx.Client.request")
    def test_search_404_raises_typed_not_found(self, mock_req, client):
        mock_req.return_value = _build_response(404, body="no such index")
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            client.search("anything")
        assert exc.value.status_code == 404
        assert exc.value.detail == "no such index"
        # Backward-compat: still a SmartMemoryClientError.
        assert isinstance(exc.value, SmartMemoryClientError)

    @patch("httpx.Client.request")
    def test_search_401_raises_typed_permission(self, mock_req, client):
        mock_req.return_value = _build_response(401, body="unauthorized")
        with pytest.raises(SmartMemoryPermissionError) as exc:
            client.search("anything")
        assert exc.value.status_code == 401

    @patch("httpx.Client.request")
    def test_search_422_raises_typed_validation(self, mock_req, client):
        mock_req.return_value = _build_response(422, body="bad query")
        with pytest.raises(SmartMemoryValidationError) as exc:
            client.search("anything")
        assert exc.value.status_code == 422

    @patch("httpx.Client.request")
    def test_search_500_raises_typed_server_with_detail(self, mock_req, client):
        mock_req.return_value = _build_response(500, body="boom")
        with pytest.raises(SmartMemoryServerError) as exc:
            client.search("anything")
        assert exc.value.status_code == 500
        assert exc.value.detail == "boom"


# ---------------------------------------------------------------------------
# summary_* — isinstance(SmartMemoryNotFoundError), not "404" substring
# ---------------------------------------------------------------------------


class TestSummaryNotFoundMechanism:
    @patch("httpx.Client.request")
    def test_summary_latest_returns_none_on_real_404(self, mock_req, client):
        mock_req.return_value = _build_response(404, body="no snapshots")
        assert client.summary_latest() is None

    @patch("httpx.Client.request")
    def test_summary_get_returns_none_on_real_404(self, mock_req, client):
        mock_req.return_value = _build_response(404, body="missing")
        assert client.summary_get("nope") is None

    @patch("httpx.Client.request")
    def test_summary_delta_returns_none_on_real_404(self, mock_req, client):
        mock_req.return_value = _build_response(404, body="missing")
        assert client.summary_delta("a", "b") is None

    @patch("httpx.Client.request")
    def test_summary_latest_500_with_404_in_body_still_raises(self, mock_req, client):
        # The crux of the correctness fix: a 500 whose body merely *contains* the
        # digits "404" must NOT be swallowed as not-found. The old substring check
        # (`"404" in str(e)`) would have wrongly returned None here.
        mock_req.return_value = _build_response(
            500, body="upstream returned 404 for dependency; this is a 500"
        )
        with pytest.raises(SmartMemoryServerError) as exc:
            client.summary_latest()
        assert exc.value.status_code == 500

    @patch("httpx.Client.request")
    def test_summary_get_403_with_404_in_body_still_raises(self, mock_req, client):
        mock_req.return_value = _build_response(403, body="error 404 not in your scope")
        with pytest.raises(SmartMemoryPermissionError) as exc:
            client.summary_get("snap")
        assert exc.value.status_code == 403

    @patch("httpx.Client.request")
    def test_summary_delta_500_with_404_in_body_still_raises(self, mock_req, client):
        mock_req.return_value = _build_response(500, body="trace id 404abc failed")
        with pytest.raises(SmartMemoryServerError):
            client.summary_delta("a", "b")


# ---------------------------------------------------------------------------
# search() — forwards documented server params
# ---------------------------------------------------------------------------


class TestSearchForwardsDocumentedParams:
    @patch("httpx.Client.request")
    def test_decompose_forwarded_when_true(self, mock_req, client):
        mock_req.return_value = _build_response(200, json_data={"results": []})
        client.search("q", decompose=True)
        body = mock_req.call_args.kwargs["json"]
        assert body.get("decompose") is True

    @patch("httpx.Client.request")
    def test_semantic_hops_forwarded_when_true(self, mock_req, client):
        mock_req.return_value = _build_response(200, json_data={"results": []})
        client.search("q", multi_hop=True, semantic_hops=True)
        body = mock_req.call_args.kwargs["json"]
        assert body.get("semantic_hops") is True

    @patch("httpx.Client.request")
    def test_include_reference_forwarded_when_true(self, mock_req, client):
        mock_req.return_value = _build_response(200, json_data={"results": []})
        client.search("q", include_reference=True)
        body = mock_req.call_args.kwargs["json"]
        assert body.get("include_reference") is True

    @patch("httpx.Client.request")
    def test_new_params_omitted_when_false(self, mock_req, client):
        # Default-off: absent from the body so server defaults apply.
        mock_req.return_value = _build_response(200, json_data={"results": []})
        client.search("q")
        body = mock_req.call_args.kwargs["json"]
        assert "decompose" not in body
        assert "semantic_hops" not in body
        assert "include_reference" not in body
