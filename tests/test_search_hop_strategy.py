from unittest.mock import Mock, patch
from smartmemory_client import SmartMemoryClient


def test_hop_strategy_and_inert_response():
    client = SmartMemoryClient(base_url="http://test", team_id="ws", api_key="fake")
    response = Mock(status_code=200, headers={})
    response.json.return_value = {
        "results": [],
        "inert_parameters": {"hop_strategy": "multi_hop is false"},
    }
    with patch("httpx.Client.request", return_value=response) as request:
        client.search("bridge", hop_strategy="relevance")
        assert request.call_args.kwargs["json"]["hop_strategy"] == "relevance"
        assert client.last_inert_parameters == {"hop_strategy": "multi_hop is false"}
        client.search("bridge")
        assert "hop_strategy" not in request.call_args.kwargs["json"]
