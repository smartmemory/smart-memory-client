"""CLIENT-2.0-DOCUMENT-INGEST-1: ``ingest_document`` mirrors JS ``ingestDocument`` with a strict receipt decode."""

import copy
import json
from pathlib import Path

import pytest

from smartmemory_client import SmartMemoryClient
from smartmemory_client.client import _exception_for_status
from smartmemory_client.errors import SmartMemoryValidationError
from smartmemory_client.receipt import ReceiptError

FX = json.loads(
    (Path(__file__).parent / "data" / "save_receipt_fixtures.json").read_text()
)
DOC_RECEIPT = {
    **FX["extracted_save"],
    "subject": {"kind": "document_save", "document_id": "doc_9"},
}
LEGACY_BODY = {"id": "doc_9", "status": "created"}  # 1.x body: no schema_version
URL = "https://example.com/paper.pdf"
# JS: ingestDocument(URL, {sourceType, chunkSize, chunkStrategy, reference, context}) posts exactly these keys
# (MemoryAPI.js:582 body: source, source_type, chunk_size, chunk_strategy, reference, context) plus the key.
JS_BODY = {
    "source": URL,
    "source_type": "pdf",
    "chunk_size": 500,
    "chunk_strategy": "markdown",
    "reference": True,
    "context": {"origin": "t"},
}


class Fake:
    def __init__(self, item):
        self.item, self.calls = item, []

    def __call__(self, method, endpoint, params=None, json_body=None, **_):
        self.calls.append((method, endpoint, copy.deepcopy(json_body)))
        if isinstance(self.item, BaseException):
            raise self.item
        return copy.deepcopy(self.item)


def run(monkeypatch, item, **kwargs):
    client = SmartMemoryClient(base_url="http://test", api_key="k", workspace_id="w")
    fake = Fake(item)
    monkeypatch.setattr(client, "_request", fake)
    return client, fake, kwargs


def call(client, kwargs):
    return client.ingest_document(kwargs.pop("source", URL), **kwargs)


def http422():
    return _exception_for_status(422)(
        "Request failed: HTTP 422", status_code=422, detail='{"detail": "non-public"}'
    )


def test_ingest_document_rows(monkeypatch):
    # row 1: terminal document_save receipt is returned, document id readable
    client, fake, kw = run(monkeypatch, DOC_RECEIPT)
    r = call(client, kw)
    method, endpoint, _ = fake.calls[0]
    assert (method, endpoint) == ("POST", "/memory/ingest/document")
    assert r.subject_kind == "document_save"
    assert r.item_id == "doc_9"

    # row 2: a 1.x body is a strict refusal, not a bridged receipt
    client, fake, kw = run(monkeypatch, LEGACY_BODY)
    with pytest.raises(ReceiptError) as exc:
        call(client, kw)
    assert exc.value.code == "not_a_receipt"

    # row 3: a 4xx from the route is the client's typed error
    client, fake, kw = run(monkeypatch, http422())
    with pytest.raises(SmartMemoryValidationError):
        call(client, kw)

    # row 4: request body fields equal JS's for the same input
    client, fake, kw = run(monkeypatch, DOC_RECEIPT)
    client.ingest_document(
        URL,
        source_type="pdf",
        chunk_size=500,
        chunk_strategy="markdown",
        reference=True,
        context={"origin": "t"},
    )
    body = fake.calls[0][2]
    assert {k: v for k, v in body.items() if k != "idempotency_key"} == JS_BODY
    assert body["idempotency_key"].startswith("sm2_")

    # row 5: omitted options are not sent (JS only sets non-null fields); a non-URL is refused before any request
    client, fake, kw = run(monkeypatch, DOC_RECEIPT)
    client.ingest_document(URL)
    assert set(fake.calls[0][2]) == {"source", "idempotency_key"}
    with pytest.raises(ValueError):
        client.ingest_document("/etc/passwd")
    assert len(fake.calls) == 1
