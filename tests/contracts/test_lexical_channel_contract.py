"""Python wire cases paired with the JS lexical contract replay."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client.client import SmartMemoryClientError

CONTRACT = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "smart-memory-docs/docs/features/CORE-LEXICAL-INDEX-1/lexical-contract.json"
    ).read_text()
)


@pytest.mark.parametrize(
    "case",
    [
        "omitted",
        "empty",
        "zero",
        "accepted",
        "contains",
        "keyword-bm25",
        "unknown",
        "validation",
        "unavailable",
    ],
)
def test_python_search_obeys_lexical_contract(case):
    client = SmartMemoryClient(base_url="http://test", team_id="ws", api_key="fake")
    options = {}
    status = {"validation": 400, "unavailable": 503}.get(case, 200)
    detail = (
        "Unmatched quotation mark in lexical query."
        if status == 400
        else "LexicalIndexUnavailableError: sm rebuild --lexical"
    )
    if case in {"empty", "zero", "accepted", "contains", "keyword-bm25", "unknown"}:
        weights = (
            {}
            if case == "empty"
            else {"lexical": 0}
            if case == "zero"
            else dict.fromkeys(CONTRACT["channels"]["accepted"], 0.8)
            if case == "accepted"
            else {case: 0}
        )
        options["channel_weights"] = weights
    response = httpx.Response(
        status,
        json={"results": []} if status == 200 else {"detail": detail},
        request=httpx.Request("POST", "http://test/memory/search"),
    )
    with patch("httpx.Client.request", return_value=response) as request:
        if case in CONTRACT["channels"]["removed"] or case == "unknown":
            with pytest.raises(ValueError) as error:
                client.search("quartz", **options)
            if case != "unknown":
                assert str(error.value) == CONTRACT["errors"]["validation"][
                    "removed_channel_message"
                ].format(channel=case)
            request.assert_not_called()
        elif status != 200:
            with pytest.raises(SmartMemoryClientError) as error:
                client.search("quartz", **options)
            assert error.value.status_code == status
            assert detail in str(error.value)
        else:
            assert client.search("quartz", **options) == []
            body = request.call_args.kwargs["json"]
            if case == "omitted":
                assert "channel_weights" not in body
            else:
                assert body["channel_weights"] == options["channel_weights"]
