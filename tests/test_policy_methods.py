"""GOV-STRATUM-SEAM-1 P1 tests for the Python client policy exchange methods."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import (
    SmartMemoryClient,
    SmartMemoryNotFoundError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)


@pytest.fixture
def client():
    return SmartMemoryClient(base_url="http://localhost:9001", api_key="test-token")


def _response(body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.text = str(body)
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def _event():
    return {
        "event_id": "run-1:ledger-1",
        "kind": "guard_transition",
        "run_id": "run-1",
        "bundle_id": "a" * 64,
        "runner": "local",
        "occurred_at": "2026-08-21T00:00:00Z",
        "outcome": "committed",
        "resolved_by": "agent",
        "rules_evaluated": [],
    }


@patch("httpx.Client.request")
def test_policy_bundle_uses_repeatable_status_params(mock_request, client):
    bundle = {"bundle_id": "a" * 64, "workspace_id": "workspace-a", "rules": []}
    mock_request.return_value = _response(bundle)

    assert (
        client.policy_bundle(
            workflow="deploy", domain="security", statuses=("active", "pending")
        )
        == bundle
    )
    assert mock_request.call_args.args == (
        "GET",
        "http://localhost:9001/memory/policy/bundle",
    )
    assert mock_request.call_args.kwargs["params"] == {
        "workflow": "deploy",
        "domain": "security",
        "status": ["active", "pending"],
    }


@patch("httpx.Client.request")
def test_record_enforcement_event_posts_the_contract_body(mock_request, client):
    result = {
        "event_id": "run-1:ledger-1",
        "item_id": "event-1",
        "created": True,
        "edges": 0,
    }
    mock_request.return_value = _response(result)

    assert client.record_enforcement_event(_event()) == result
    assert mock_request.call_args.args == (
        "POST",
        "http://localhost:9001/memory/policy/events",
    )
    assert mock_request.call_args.kwargs["json"] == _event()


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, SmartMemoryValidationError),
        (404, SmartMemoryNotFoundError),
        (500, SmartMemoryServerError),
    ],
)
@patch("httpx.Client.request")
def test_policy_bundle_maps_http_errors(mock_request, client, status, error_type):
    response = _response({"detail": "failure"}, status_code=status)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=response
    )
    mock_request.return_value = response

    with pytest.raises(error_type) as error:
        client.policy_bundle()
    assert error.value.status_code == status


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, SmartMemoryValidationError),
        (404, SmartMemoryNotFoundError),
        (500, SmartMemoryServerError),
    ],
)
@patch("httpx.Client.request")
def test_record_enforcement_event_maps_http_errors(
    mock_request, client, status, error_type
):
    response = _response({"detail": "failure"}, status_code=status)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=response
    )
    mock_request.return_value = response

    with pytest.raises(error_type) as error:
        client.record_enforcement_event(_event())
    assert error.value.status_code == status
