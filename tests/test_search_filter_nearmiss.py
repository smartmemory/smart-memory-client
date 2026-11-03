"""DEV-ONBOARD-FU-SCOPED-SEARCH-NEARMISS-1: a misspelt filter keyword never becomes an unfiltered search.

`search()` has no `**kwargs`, so Python itself rejects an unknown keyword with a TypeError before any request.
These rows pin that, so adding a `**kwargs` later (which would swallow the typo) turns this file red.
"""

from unittest.mock import patch

import pytest

from smartmemory_client import SmartMemoryClient

# Same set the service refuses with a 422, plus the camelCase option name the JS SDK uses.
NEAR_MISS = [
    "filters",
    "filter",
    "metadata_filters",
    "metadataFilter",
    "metadataFilters",
    "where",
    "meta_filter",
]

NOT_A_DICT = [
    pytest.param("cus_1", id="str"),
    pytest.param(["customer_id", "cus_1"], id="list"),
    pytest.param((("customer_id", "cus_1"),), id="tuple"),
    pytest.param(5, id="int"),
    pytest.param(True, id="bool"),
]


def _client():
    return SmartMemoryClient(base_url="http://test", team_id="ws", api_key="fake")


@pytest.mark.parametrize("name", NEAR_MISS)
def test_near_miss_keyword_is_a_typeerror_before_any_request(name):
    with patch("httpx.Client.request") as request, pytest.raises(TypeError, match=name):
        _client().search("q", **{name: {"customer_id": "cus_1"}})
    assert not request.called


@pytest.mark.parametrize("value", NOT_A_DICT)
def test_non_dict_metadata_filter_is_refused_before_any_request(value):
    with (
        patch("httpx.Client.request") as request,
        pytest.raises(ValueError, match="must be a dict"),
    ):
        _client().search("q", metadata_filter=value)
    assert not request.called
