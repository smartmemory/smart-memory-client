from unittest.mock import Mock, patch
from datetime import datetime
from smartmemory_client import SmartMemoryClient


def test_both_search_requests_and_coverage():
    client = SmartMemoryClient(base_url="http://test", team_id="ws", api_key="fake")
    response = Mock(status_code=200, headers={})
    response.json.return_value = {
        "results": [],
        "coverage": {"created_at_backfilled_boundary": None},
    }
    with patch("httpx.Client.request", return_value=response) as request:
        client.search("atlas", since=datetime(2026, 9, 1), until="2026-09-03")
        assert request.call_args.kwargs["json"]["since"] == "2026-09-01T00:00:00"
        assert request.call_args.kwargs["json"]["until"] == "2026-09-03"
        assert client.last_search_coverage == {"created_at_backfilled_boundary": None}
    with patch.object(client, "_request", return_value={}) as request:
        client.search_by_metadata("project", "atlas", since="2026-09-01")
        assert request.call_args.kwargs["params"]["since"] == "2026-09-01"
        assert "until" not in request.call_args.kwargs["params"]
