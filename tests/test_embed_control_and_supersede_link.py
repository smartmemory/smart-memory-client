"""SVC-EMBED-CONTROL-1 + SVC-SUPERSEDE-LINK-1 — Python SDK surface.

Contract-checked against the feature contracts: wire field names and the URL
must match exactly, since forge/compose reads those contracts rather than this
SDK and a divergence here would not fail anywhere else.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client.client import (
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

FEATURES = (
    Path(__file__).resolve().parents[2] / "smart-memory-docs" / "docs" / "features"
)
EMBED_CONTRACT = FEATURES / "SVC-EMBED-CONTROL-1" / "embed-control-contract.json"
LINK_CONTRACT = FEATURES / "SVC-SUPERSEDE-LINK-1" / "supersede-link-contract.json"


def _mock_response(json_payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status: int):
    resp = MagicMock()
    resp.status_code = status
    resp.text = "error"
    resp.headers = {}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=resp
    )
    return resp


def _client():
    return SmartMemoryClient(
        base_url="http://localhost:9001", team_id="team-test", api_key="key-test"
    )


class TestEmbedControl:
    def _add_body(self, **kwargs):
        captured = {}

        def fake_request(method, url, json=None, headers=None, timeout=None, **kw):
            captured["body"] = json
            return _mock_response({"item_id": "m-1"})

        with patch("httpx.Client.request", side_effect=fake_request):
            _client().add("content", use_pipeline=False, **kwargs)
        return captured["body"]

    def test_omitted_embed_is_absent_from_the_wire(self):
        """The additive guarantee — an omitted arg must not appear as null."""
        assert "embed" not in self._add_body()

    def test_embed_false_forwarded(self):
        assert self._add_body(embed=False)["embed"] is False

    def test_embed_true_forwarded(self):
        assert self._add_body(embed=True)["embed"] is True

    def test_wire_field_name_matches_contract(self):
        contract = json.loads(EMBED_CONTRACT.read_text())
        assert contract["field"]["name"] == "embed"
        assert "embed" in self._add_body(embed=True)


class TestSupersedeLink:
    def _call(self, response, **kwargs):
        captured = {}

        def fake_request(method, url, json=None, headers=None, timeout=None, **kw):
            captured["url"] = url
            captured["body"] = json
            captured["method"] = method
            return response

        with patch("httpx.Client.request", side_effect=fake_request):
            result = _client().supersede_link("old-1", "new-1", **kwargs)
        return result, captured

    def test_happy_path_url_and_body_match_contract(self):
        contract = json.loads(LINK_CONTRACT.read_text())
        endpoint = contract["endpoints"]["supersede_link"]

        payload = {
            "status": "superseded",
            "old_item_id": "old-1",
            "new_item_id": "new-1",
            "superseded_at": "2026-08-05T09:27:11+00:00",
        }
        result, captured = self._call(_mock_response(payload), reason="because")

        assert captured["method"] == "POST"
        assert captured["url"].endswith("/memory/old-1/supersede-link")
        assert endpoint["path"] == "/memory/{item_id}/supersede-link"
        assert captured["body"] == {"new_item_id": "new-1", "reason": "because"}
        assert set(endpoint["request_body"]) == set(captured["body"])
        assert result["superseded_at"] == "2026-08-05T09:27:11+00:00"

    def test_reason_defaults_to_none(self):
        _, captured = self._call(_mock_response({"status": "superseded"}))
        assert captured["body"]["reason"] is None

    def test_self_supersession_400_is_validation_error(self):
        with pytest.raises(SmartMemoryValidationError) as exc:
            self._call(_error_response(400))
        assert exc.value.status_code == 400

    def test_inaccessible_404_is_not_found(self):
        with pytest.raises(SmartMemoryNotFoundError) as exc:
            self._call(_error_response(404))
        assert exc.value.status_code == 404

    def test_store_refusal_409_is_validation_error(self):
        with pytest.raises(SmartMemoryValidationError) as exc:
            self._call(_error_response(409))
        assert exc.value.status_code == 409

    def test_server_error_500(self):
        with pytest.raises(SmartMemoryServerError) as exc:
            self._call(_error_response(500))
        assert exc.value.status_code == 500
