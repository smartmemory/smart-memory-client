from unittest.mock import Mock

from smartmemory_client import SmartMemoryClient


def _client() -> SmartMemoryClient:
    client = SmartMemoryClient.__new__(SmartMemoryClient)
    client._request = Mock(return_value={})
    return client


def test_system_team_contract_is_explicit_and_additive():
    client = _client()

    client.create_team("Maya", is_system=True)
    client._request.assert_called_with(
        "POST",
        "/memory/teams",
        json_body={
            "name": "Maya",
            "description": None,
            "data_classification": "internal",
            "cost_center": None,
            "is_system": True,
        },
    )

    client.list_teams(include_system=True)
    client._request.assert_called_with(
        "GET", "/memory/teams", params={"include_system": True}
    )


def test_generic_supersession_contract():
    client = _client()

    client.supersede(
        "old-opinion",
        content="Revised view",
        memory_type="opinion",
        metadata={"maya_self_origin": "experience"},
        reason="New evidence",
    )

    client._request.assert_called_with(
        "POST",
        "/memory/old-opinion/supersede",
        json_body={
            "content": "Revised view",
            "memory_type": "opinion",
            "metadata": {"maya_self_origin": "experience"},
            "reason": "New evidence",
        },
    )
