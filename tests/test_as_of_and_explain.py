"""PLAT-AUDITABLE-MEMORY-1 — Python SDK as-of search params + explain().

Contract tests against explain-contract.json: field names in the search body
must match the SearchRequest contract exactly; the explain response shape is
asserted against the contract's required top-level blocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client.client import SmartMemoryNotFoundError

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "smart-memory-docs"
    / "docs"
    / "features"
    / "PLAT-AUDITABLE-MEMORY-1"
    / "explain-contract.json"
)


def _mock_response(json_payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp


def _client():
    return SmartMemoryClient(
        base_url="http://localhost:9001", team_id="team-test", api_key="key-test"
    )


class TestSearchAsOfParams:
    def _search_body(self, **kwargs):
        client = _client()
        captured = {}

        def fake_request(method, url, json=None, headers=None, timeout=None, **kw):
            captured["body"] = json
            return _mock_response([])

        with patch("httpx.Client.request", side_effect=fake_request):
            client.search("q", **kwargs)
        return captured["body"]

    def test_defaults_omit_both(self):
        body = self._search_body()
        assert "as_of_date" not in body
        assert "include_superseded" not in body

    def test_iso_string_forwarded_verbatim(self):
        body = self._search_body(as_of_date="2026-01-01T00:00:00+00:00")
        assert body["as_of_date"] == "2026-01-01T00:00:00+00:00"

    def test_datetime_serialized_to_iso(self):
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        body = self._search_body(as_of_date=dt)
        assert body["as_of_date"] == "2026-01-01T00:00:00+00:00"

    def test_include_superseded_forwarded(self):
        body = self._search_body(include_superseded=True)
        assert body["include_superseded"] is True


class TestExplain:
    def test_explain_hits_explain_route(self):
        client = _client()
        payload = {
            "item": {"id": "m1"},
            "versions": [],
            "supersession": [],
            "lineage_roots": ["m1"],
            "decision_provenance": {"self": None, "citing_decisions": []},
            "status_flags": {"has_version_chain": False, "resolution_errors": []},
            "chain_verified": None,
        }
        with patch.object(client, "_request", return_value=payload) as req:
            result = client.explain("m1")
        req.assert_called_once_with("GET", "/memory/m1/explain")
        assert result["item"]["id"] == "m1"

    def _status_response(self, status: int, text: str = "err"):
        import httpx

        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status), request=MagicMock(), response=resp
        )
        return resp

    def test_explain_404_raises_not_found(self):
        client = _client()
        with patch("httpx.Client.request", return_value=self._status_response(404)):
            with pytest.raises(SmartMemoryNotFoundError) as exc_info:
                client.explain("missing")
        assert exc_info.value.status_code == 404

    def test_explain_400_raises_validation(self):
        from smartmemory_client import SmartMemoryValidationError

        client = _client()
        with patch("httpx.Client.request", return_value=self._status_response(400)):
            with pytest.raises(SmartMemoryValidationError):
                client.explain("bad id")

    def test_explain_500_raises_server_error(self):
        from smartmemory_client import SmartMemoryServerError

        client = _client()
        with patch("httpx.Client.request", return_value=self._status_response(500)):
            with pytest.raises(SmartMemoryServerError):
                client.explain("m1")

    def test_explain_none_response_raises_not_found(self):
        client = _client()
        with patch.object(client, "_request", return_value=None):
            with pytest.raises(SmartMemoryNotFoundError):
                client.explain("missing")

    @pytest.mark.skipif(
        not CONTRACT_PATH.exists(), reason="explain-contract.json not checked out"
    )
    def test_contract_top_level_blocks_covered(self):
        """Every required top-level ExplainResponse field appears in the shape
        this SDK returns verbatim (the SDK passes the body through — this
        pins the contract fields so a server-side rename fails here)."""
        contract = json.loads(CONTRACT_PATH.read_text())
        required = [k for k in contract["ExplainResponse"] if not k.startswith("_")]
        payload = {
            "item": {},
            "versions": [],
            "supersession": [],
            "lineage_roots": ["x"],
            "decision_provenance": {"self": None, "citing_decisions": []},
            "status_flags": {},
            "chain_verified": None,
        }
        assert sorted(required) == sorted(payload.keys())
