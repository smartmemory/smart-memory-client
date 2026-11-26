"""Contract and recorded preview from graph fcd8284, contracts/decision-effects.json
and tests/fixtures/decisionEffects.js (email.decisionEffects).
"""

import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from smartmemory_client import (
    SmartMemoryClient,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryRateLimitError,
    SmartMemoryServerError,
    SmartMemoryValidationError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "decision_effects"
CONTRACT = json.loads((FIXTURES / "decision-effects.json").read_text())
DRAFT = "Move email delivery to the US."
RESOLUTIONS = {"eu": {"choice": "keep_both_scoped", "scope": "EU customers"}}
ROUTES = [
    (
        "get_decision_effects",
        ("d ?",),
        "GET",
        "d%20%3F/effects",
        None,
        "EffectsRequest",
    ),
    (
        "preview_decision_effects",
        (DRAFT,),
        "POST",
        "effects/preview",
        {"text": DRAFT},
        "PreviewRequest",
    ),
    (
        "commit_decision_effects",
        (DRAFT, RESOLUTIONS),
        "POST",
        "effects/commit",
        {"text": DRAFT, "resolutions": RESOLUTIONS},
        "CommitRequest",
    ),
    (
        "add_decision_depends_on",
        ("d ?", "eu"),
        "POST",
        "d%20%3F/depends-on",
        {"target_id": "eu"},
        "DependsOnRequest",
    ),
    (
        "confirm_decision_depends_on",
        ("d ?", "eu#"),
        "POST",
        "d%20%3F/depends-on/eu%23/confirm",
        None,
        None,
    ),
    (
        "remove_decision_depends_on",
        ("d ?", "eu#"),
        "DELETE",
        "d%20%3F/depends-on/eu%23",
        None,
        None,
    ),
]


def validate(definition, instance):
    schema = {**CONTRACT, "$ref": f"#/$defs/{definition}"}
    Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    ).validate(instance)


@pytest.fixture
def transport():
    requests = []
    client = SmartMemoryClient(
        base_url="https://effects.invalid",
        api_key="fixture",
        workspace_id="effects-test",
    )
    client.close()

    def setup(status, reply):
        def handle(request):
            requests.append(request)
            return httpx.Response(status, json=reply, headers={"Retry-After": "12"})

        client._client = httpx.Client(transport=httpx.MockTransport(handle))
        return client, requests

    yield setup
    client.close()


@pytest.mark.parametrize("name,args,verb,path,body,definition", ROUTES)
def test_wire_request(transport, name, args, verb, path, body, definition):
    reply = {"source": "d ?", "target": "eu", "type": "depends_on"}
    if name in (
        "get_decision_effects",
        "preview_decision_effects",
        "commit_decision_effects",
    ):
        reply = json.loads((FIXTURES / "email-preview.json").read_text())
    client, requests = transport(200, reply)
    result = getattr(client, name)(*args)
    assert result == reply
    (request,) = requests
    assert request.method == verb
    assert request.url.raw_path.decode() == f"/memory/decisions/{path}"
    assert request.headers["Authorization"] == "Bearer fixture"
    assert request.headers["X-Workspace-Id"] == "effects-test"
    if body is None:
        assert request.content == b""
    else:
        assert json.loads(request.content) == body
    if definition:
        validate(
            definition,
            json.loads(request.content)
            if body is not None
            else {"id": request.url.path.split("/")[3]},
        )
    if name == "preview_decision_effects":
        validate("DecisionEffectsSnapshot", result)
        assert result["counts"] == {"conflicts": 1, "replaced": 1, "to_review": 3}
        assert result["whyPaths"]["exports"] == [
            "legal",
            "eu",
            "vendor",
            "support",
            "exports",
        ]


def test_dated_preview_preserves_suggestions(transport):
    reply = json.loads((FIXTURES / "email-preview.json").read_text())
    reply["data"]["edges"][0]["suggested"] = True
    reply["data"]["nodes"][0]["viaSuggested"] = True
    reply.update(
        suggestedLinks="dashed",
        suggestions=[{"source": "support", "target": "vendor", "reason": "Email"}],
    )
    client, requests = transport(200, reply)
    assert client.preview_decision_effects(DRAFT, as_of=reply["today"]) == reply
    body = json.loads(requests[0].content)
    assert body == {"text": DRAFT, "as_of": reply["today"]}
    validate("PreviewRequest", body)


@pytest.mark.parametrize("name,args", [row[:2] for row in ROUTES])
@pytest.mark.parametrize(
    "status,error",
    [
        (400, SmartMemoryValidationError),
        (401, SmartMemoryPermissionError),
        (403, SmartMemoryPermissionError),
        (404, SmartMemoryNotFoundError),
        (429, SmartMemoryRateLimitError),
        (500, SmartMemoryServerError),
    ],
)
def test_route_errors(transport, name, args, status, error):
    client, requests = transport(status, {"detail": "refused"})
    with pytest.raises(error) as caught:
        getattr(client, name)(*args)
    assert caught.value.status_code == status
    assert len(requests) == 1
    if status == 429:
        assert caught.value.retry_after_s == 12


def test_unsettled_commit_exposes_missing_ids(transport):
    refusal = {"conflict_ids": ["eu"]}
    validate("UnsettledConflict", refusal)
    client, requests = transport(409, refusal)
    with pytest.raises(SmartMemoryValidationError) as caught:
        client.commit_decision_effects(DRAFT, {})
    assert caught.value.status_code == 409
    assert json.loads(caught.value.detail) == refusal
    (request,) = requests
    assert json.loads(request.content) == {"text": DRAFT, "resolutions": {}}


@pytest.mark.parametrize(
    "name", ["confirm_decision_depends_on", "remove_decision_depends_on"]
)
def test_target_cannot_leave_route(transport, name):
    client, requests = transport(200, {})
    with pytest.raises(ValueError):
        getattr(client, name)("d", "../other")
    assert requests == []
