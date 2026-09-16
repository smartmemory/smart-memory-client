from unittest.mock import Mock, patch

from smartmemory_client import SmartMemoryClient


def test_search_sends_reranker_only_when_set():
    client = SmartMemoryClient(
        base_url="http://test", workspace_id="ws", api_key="fake"
    )
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"results": []}

    with patch("httpx.Client.request", return_value=response) as request:
        client.search("quartz", reranker="none")
        assert request.call_args.kwargs["json"]["reranker"] == "none"

        client.search("quartz")
        assert "reranker" not in request.call_args.kwargs["json"]
