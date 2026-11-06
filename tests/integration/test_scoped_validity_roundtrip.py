"""Real HTTP U09 golden flows. The local harness supplies URL and disposable owners."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from smartmemory_client import (
    SmartMemoryClient,
    SmartMemoryValidationError,
    SmartMemoryPermissionError,
    SmartMemoryNotFoundError,
)

pytestmark = [pytest.mark.integration, pytest.mark.golden]


@pytest.fixture(scope="module")
def sdk():
    url = os.environ[
        "SCOPED_VALIDITY_SERVICE_URL"
    ]  # required, never skip the golden gate
    owners = json.loads(os.environ["SCOPED_VALIDITY_TEST_OWNERS"])
    clients = [
        SmartMemoryClient(
            base_url=url, token=o["access_token"], workspace_id=o["workspace_id"]
        )
        for o in owners
    ]
    try:
        yield clients
    finally:
        for client in clients:
            client.close()


@pytest.fixture(scope="module")
def card():
    return json.loads(Path(os.environ["SCOPED_VALIDITY_FIXTURE"]).read_text())


@pytest.fixture(scope="module")
def golden(sdk, card):
    client = sdk[0]
    old = client.create_decision(
        card["versions"][0]["content"],
        scope_go_lives=card["versions"][0]["scope_go_lives"],
    )["decision_id"]
    before = datetime.now(timezone.utc).isoformat()
    receipt = client.supersede_decision(
        old,
        card["versions"][1]["content"],
        "clinical amendment",
        scope_go_lives=card["versions"][1]["scope_go_lives"],
    )
    assert receipt["status"] == "scheduled"
    return {"v1": old, "v2": receipt["new_item_id"]}, before


def test_G01_G05_boundaries_readback(sdk, card, golden):
    ids, _ = golden
    for row in card["queries"]:
        options = {"valid_at": row["valid_at"]}
        if row["site"] is not None:
            options["business_scope"] = {"site": row["site"]}
        result = sdk[0].get_decision(ids["v2"], **options)
        assert result["decision_id"] == ids[row["expected"]], row
        assert result["content"] == next(
            v["content"] for v in card["versions"] if v["id"] == row["expected"]
        )
        assert "scope_go_lives" in result


def test_G06_read_surfaces_and_search(sdk, golden):
    ids, _ = golden
    client = sdk[0]
    opts = {"business_scope": {"site": "B"}, "valid_at": "2026-02-08T00:00:00Z"}
    assert [d["decision_id"] for d in client.list_decisions(**opts)] == [ids["v1"]]
    assert [
        d["decision_id"]
        for d in client.search_decisions("CRF guidance", **opts)["decisions"]
    ] == [ids["v1"]]
    assert (
        client.get_provenance_chain(ids["v2"], **opts)["decision"]["decision_id"]
        == ids["v1"]
    )
    results = client.search(
        "Amended CRF guidance", top_k=1, memory_type="decision", **opts
    )
    assert [r.item_id for r in results] == [ids["v1"]]
    assert results[0].content == "Original CRF guidance"


def test_G07_tenant_and_workspace_isolation(sdk, golden, card):
    ids, _ = golden
    for other in sdk[1:]:
        with pytest.raises(SmartMemoryNotFoundError):
            other.get_decision(ids["v1"], business_scope={"site": "A"})
        own = other.create_decision(
            "isolated CRF", scope_go_lives=card["versions"][0]["scope_go_lives"]
        )["decision_id"]
        assert (
            other.get_decision(own, business_scope={"site": "A"})["content"]
            == "isolated CRF"
        )
        assert ids["v1"] not in [
            d["decision_id"] for d in other.list_decisions(business_scope={"site": "A"})
        ]


def test_G08_legacy_and_generic_replacements(sdk, card):
    client = sdk[0]
    legacy = client.create_decision("legacy old")["decision_id"]
    receipt = client.supersede_decision(legacy, "legacy new", "global")
    assert receipt["status"] == "superseded"
    assert client.get_decision(receipt["new_decision_id"])["content"] == "legacy new"
    for link in (False, True):
        old = client.create_decision(
            "generic original", scope_go_lives=card["versions"][0]["scope_go_lives"]
        )["decision_id"]
        schedule = card["versions"][1]["scope_go_lives"]
        if link:
            new = client.create_decision("generic amendment")["decision_id"]
            result = client.supersede_link(
                old, new, "link amendment", scope_go_lives=schedule
            )
        else:
            result = client.supersede(
                old,
                content="generic amendment",
                memory_type="decision",
                reason="create amendment",
                scope_go_lives=schedule,
            )
        assert result["status"] == "scheduled"
        assert (
            client.get_decision(
                old, business_scope={"site": "B"}, valid_at="2026-02-08T00:00:00Z"
            )["decision_id"]
            == old
        )
        assert (
            client.get_decision(
                old, business_scope={"site": "A"}, valid_at="2026-02-08T00:00:00Z"
            )["decision_id"]
            == result["new_item_id"]
        )


def test_G11_typed_validation_conflict_auth(sdk, golden, card):
    client = sdk[0]
    ids, _ = golden
    for schedule in ([], card["versions"][1]["scope_go_lives"] * 2):
        with pytest.raises(SmartMemoryValidationError) as error:
            client.supersede_link(ids["v1"], ids["v2"], scope_go_lives=schedule)
        assert error.value.status_code == 400
        assert "invalid_scoped_validity" in error.value.detail
    with pytest.raises(SmartMemoryValidationError) as error:
        client.supersede_decision(
            ids["v1"],
            "conflict",
            "conflict",
            scope_go_lives=[
                {"scope": {"site": "A"}, "valid_from": "2026-04-01T00:00:00Z"}
            ],
        )
    assert error.value.status_code == 409
    assert "scoped_validity_conflict" in error.value.detail
    with SmartMemoryClient(
        base_url=os.environ["SCOPED_VALIDITY_SERVICE_URL"], token="invalid"
    ) as unauthorized:
        with pytest.raises(SmartMemoryPermissionError) as error:
            unauthorized.get_decision(ids["v1"], business_scope={"site": "A"})
        assert error.value.status_code in (401, 403)


def test_G12_transaction_time_independent(sdk, golden):
    ids, before = golden
    client = sdk[0]
    opts = {"business_scope": {"site": "A"}, "valid_at": "2026-02-08T00:00:00Z"}
    assert (
        client.get_decision(ids["v1"], as_of=before, **opts)["decision_id"] == ids["v1"]
    )
    assert client.get_decision(ids["v1"], **opts)["decision_id"] == ids["v2"]
    assert [
        r.item_id
        for r in client.search(
            "CRF guidance", top_k=1, memory_type="decision", as_of_date=before, **opts
        )
    ] == [ids["v1"]]

    known_before_correction = datetime.now(timezone.utc).isoformat()
    client.update(
        ids["v2"],
        properties={
            "scope_go_lives": [
                {"scope": {"site": "A"}, "valid_from": "2026-02-10T00:00:00Z"},
                {"scope": {"site": "B"}, "valid_from": "2026-02-15T00:00:00Z"},
            ]
        },
    )
    assert (
        client.get_decision(ids["v1"], as_of=known_before_correction, **opts)[
            "decision_id"
        ]
        == ids["v2"]
    )
    assert client.get_decision(ids["v1"], **opts)["decision_id"] == ids["v1"]
    for recorded, expected in [
        (known_before_correction, ids["v2"]),
        (datetime.now(timezone.utc).isoformat(), ids["v1"]),
    ]:
        results = client.search(
            "Amended CRF guidance",
            top_k=1,
            memory_type="decision",
            as_of_date=recorded,
            **opts,
        )
        assert [r.item_id for r in results] == [expected]


def test_G16_missing_date_and_invalid_qualifiers(sdk, golden):
    ids, _ = golden
    client = sdk[0]
    assert (
        client.get_decision(ids["v1"], business_scope={"site": "A"})["decision_id"]
        == ids["v2"]
    )
    for options in (
        {"business_scope": {"country": "US"}},
        {"valid_at": "bad"},
        {"business_scope": {"site": "A"}, "include_superseded": True},
    ):
        with pytest.raises(SmartMemoryValidationError) as error:
            client.search("", **options)
        assert error.value.status_code == 400
