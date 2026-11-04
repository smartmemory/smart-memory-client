"""SM-LEARNED-TOOLS-1 (G7): the Python client's ``add_learning`` and ``add_constraint``.

Each row asserts the route and the exact body, that unset fields are not sent, and that a server refusal is raised.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smartmemory_client.client import SmartMemoryClient

BASE_URL = "http://localhost:9001"


@pytest.fixture
def client() -> SmartMemoryClient:
    return SmartMemoryClient(
        base_url=BASE_URL, api_key="test-token", workspace_id="workspace-test"
    )


def _response(status_code: int, json_data: dict | None = None) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = str(json_data or "")
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code} Error",
            request=MagicMock(spec=httpx.Request),
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    response.json.return_value = json_data if json_data is not None else {}
    return response


class TestAddLearning:
    @patch("httpx.Client.request")
    def test_posts_every_field_to_the_learned_route(self, mock_request, client):
        stored = {
            "item_id": "learned_1",
            "learned_id": "learned_1",
            "content": "c",
            "category": "ops",
        }
        mock_request.return_value = _response(200, stored)

        result = client.add_learning(
            "c", category="ops", incident_link="INC-7", learned_scope="repo"
        )

        assert result == stored
        assert mock_request.call_args.args == ("POST", f"{BASE_URL}/memory/learned")
        assert mock_request.call_args.kwargs["json"] == {
            "content": "c",
            "category": "ops",
            "incident_link": "INC-7",
            "learned_scope": "repo",
        }

    @patch("httpx.Client.request")
    def test_unset_fields_are_not_sent(self, mock_request, client):
        mock_request.return_value = _response(200, {"item_id": "learned_1"})

        client.add_learning("only the lesson")

        assert mock_request.call_args.kwargs["json"] == {"content": "only the lesson"}

    def test_a_root_scope_is_not_a_parameter(self, client):
        with pytest.raises(TypeError):
            client.add_learning("c", scope="other-workspace")
        with pytest.raises(TypeError):
            client.add_learning("c", workspace_id="other-workspace")

    @patch("httpx.Client.request")
    def test_a_read_only_refusal_is_raised(self, mock_request, client):
        mock_request.return_value = _response(403, {"detail": "read-only"})

        with pytest.raises(Exception) as raised:
            client.add_learning("c")

        assert "403" in str(raised.value) or "read-only" in str(raised.value)


class TestAddConstraint:
    @patch("httpx.Client.request")
    def test_posts_every_field_to_the_constraints_route(self, mock_request, client):
        stored = {
            "item_id": "constraint_1",
            "constraint_id": "constraint_1",
            "domain": "release",
        }
        mock_request.return_value = _response(200, stored)

        result = client.add_constraint(
            "never publish an sdist",
            domain="release",
            source="owner",
            expires_at="2030-01-01T00:00:00Z",
        )

        assert result == stored
        assert mock_request.call_args.args == ("POST", f"{BASE_URL}/memory/constraints")
        assert mock_request.call_args.kwargs["json"] == {
            "content": "never publish an sdist",
            "domain": "release",
            "source": "owner",
            "expires_at": "2030-01-01T00:00:00Z",
        }

    @patch("httpx.Client.request")
    def test_unset_fields_are_not_sent(self, mock_request, client):
        mock_request.return_value = _response(200, {"item_id": "constraint_1"})

        client.add_constraint("a rule")

        assert mock_request.call_args.kwargs["json"] == {"content": "a rule"}

    def test_a_root_scope_is_not_a_parameter(self, client):
        with pytest.raises(TypeError):
            client.add_constraint("c", scope="other-workspace")
