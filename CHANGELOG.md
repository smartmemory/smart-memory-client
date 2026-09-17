# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

### Added (2026-09-18) — workspace naming and typed session (AUTH-IDENTITY-MODEL-1 Phase 3)

- `workspace_id` is now the primary property; `team_id` delegates to it and keeps the
  `X-Workspace-Id` header in sync, so existing code is unaffected. `SMARTMEMORY_WORKSPACE_ID` is
  preferred over `SMARTMEMORY_TEAM_ID`, which still works.
- `get_me()` and `refresh_token()` return a typed, dict-compatible `SessionResponse` carrying
  `default_workspace_id`, `active_workspace_id`, `tenant_id` and `tenant_role`, falling back to the
  server's deprecated `default_team_id`. Existing callers that index the result as a dict keep
  working.
- Team-management methods targeting `/memory/teams` are genuine Team APIs and are unchanged.

### Added (2026-09-16) — switchable reranker policy (CORE-RERANK-PLUGIN-1)

- `SmartMemoryClient.search(reranker=...)` forwards an explicit reranker override
  and omits the field when the caller wants server-side policy resolution.

### Fixed (2026-09-10) — decision supersession context

- `supersede_decision` accepts and forwards optional `rejected_alternatives`, `rationale`, and
  `constraints` using the canonical service field names.


### Documentation (2026-09-10) — decision belief reads (CORE-DECISION-BELIEF-SURFACE-1)

- `get_decision`, `list_decisions` and `search_decisions` document the three Dempster-Shafer belief reads
  the service now returns: `belief_hold`, `plausibility_hold` and `ignorance`. All three pass through
  unchanged, so there is no code change and no version bump; core's `VERSION` is the release dial.
- The docstrings state what the fields mean and, more usefully, what they are not: they are evidence-only
  and independent of the prior scalar `confidence`, and they separate a disputed decision (high `contest`)
  from one nothing has evidenced yet (high `ignorance`), which `stability` cannot do because it reads 0.5
  for both.


### Added (2026-09-06) — optional request correlation and per-call timing hooks (MAYA-ENDPOINT-VISIBILITY-1)

- `SmartMemoryClient(request_id_provider=..., on_remote_call=...)`. The provider supplies an
  `X-Request-Id` per request so a caller's logs can be joined to the service's; the observer
  receives a `RemoteCallTiming` (method, path, status, `wall_ms`, `server_ms`, `request_id`)
  after every response, letting a caller attribute its own latency to remote service work.
- `RemoteCallTiming` is exported from the package. `server_ms` is `None`, never `0.0`, when the
  service sent no `X-SM-Latency-Ms` header — a zero would claim the service answered instantly.
- Implemented as httpx event hooks, so calls that bypass the internal request helper (health,
  search session) are covered too.
- Both hooks are failure-isolated: one that raises logs a WARNING naming what was lost and the
  request proceeds. An id that fails validation is dropped with a warning rather than sent.
- Neither hook is called for a request that failed before a response (connect/timeout); those
  raise to the caller as before.


### Changed (2026-09-06) — `personalize()` and `ground()` document their 501 (CORE-PERSONALIZATION-CONTRACT-1, CORE-GROUND-ROUTE-CONTRACT-1)

- Both methods remain on the client but state that the endpoint returns HTTP 501 because the
  feature is not implemented server-side. They previously read as working calls.

### Added (2026-09-06) — `since`/`until`, `hop_strategy`, conversation context

- `search()` and `search_by_metadata()` accept `since`/`until` creation windows and retain the
  server's coverage block in `last_search_coverage` (SEARCH-TIME-RANGE-1).
- `search()` accepts `hop_strategy` and retains the server's inert-parameter diagnostics
  (SEARCH-HOP-STRATEGY-SURFACE-1).
- Conversation ingestion accepts optional `context` so caller origin reaches the service
  (CORE-ORIGIN-PROPAGATION-1).

### Added (2026-08-22) — `include_archived` on `search()` (CORE-ARCHIVED-RECALL-1)

- `search()` gains `include_archived: bool = False`, sent only when true (same
  send-only-when-true shape as `include_superseded` / `include_retracted`, which
  also keeps an older server from rejecting an unknown field).
- Third sibling of the other two lifecycle flags. An archived item — retired by
  the decay/prune evolvers, or the source an episodic→semantic promotion replaced
  — has no replacement and no version chain, so it gets its own knob rather than
  riding `include_superseded`. Also inert under `as_of_date`.
- **The default changed behaviour rather than preserving it.** Until
  CORE-ARCHIVED-RECALL-1 the server read `archived` on no search path at all, so
  archived items were returned ranked like live ones. Callers who want them must
  now pass `include_archived=True`.


## [Unreleased]

### Changed: CORE-LEXICAL-INDEX-1 consumer cutover
- R-E4: Pin lexical HTTP contract v2 to exact 400/503 detail envelopes and verify consumer error fidelity.

- Use one `lexical` channel with default weight 0.8. Removed channel names fail validation, explicit zero is preserved, and unavailable required lexical search fails without partial success.
- Coordinated service, common, Python, JS, MCP and lite contracts cover migration and recovery. See [migration guidance](https://github.com/smart-memory/smart-memory-docs/blob/main/docs/features/CORE-LEXICAL-INDEX-1/migration.md) and the [canonical contract](https://github.com/smart-memory/smart-memory-docs/blob/main/docs/features/CORE-LEXICAL-INDEX-1/lexical-contract.json).
- Release remains pending maintainer review of measured write cost and final verification. No version bump.

### Added (2026-09-08) — rerank evidence (CORE-RERANK-EXPOSE-1)

- Preserve nullable rerank_score, reason status, actual model identity and pool diagnostics through MemoryItem.from_dict/to_dict; missing legacy evidence stays unverified.


### Added (2026-09-07) — list grounding policy (PLAT-RETRIEVAL-POLICY-1 slice 1)

- `list_memories(include_grounding=None)` inherits workspace then env defaults (OFF unless
  configured); explicit `False` and `True` are sent. The response retains the resolved
  `policy.include_grounding` and `policy.source` fields. No SDK version bump.


- fix(memory): add optional memory_type to list_memories, composed with metadata filters and applied server-side before pagination/counting.

### Added

- `search()` now accepts `exclude_speculative: bool = False` and sends it only
  when true, allowing callers to omit origin tier-3 speculative derived items
  (PLAT-MCP-HOSTED-1 / CORE-ORIGIN-1).

## [1.4.86] - 2026-09-04

### Added (2026-09-04) — `ask()` (DIST-LITE-9)

- `client.ask(question, limit=5, reasoning=True)` calls `POST /memory/ask` and returns
  `{answer, reasoning, evidence, relations}`. Unlike `search()`, which hands back ranked
  memories to read, this returns a written answer together with the evidence behind it.
- `reasoning=True` is not sent on the wire, so this client, the JS SDK and the lite
  daemon all put the same body up for the same call.
- Relation rows carry `source_id` / `target_id` as well as display labels, so a UI can
  focus the graph edge a relation names.
- No fallback answer: a server that cannot answer raises `SmartMemoryServerError` (502)
  rather than returning an empty one.

### Added — policy exchange client methods (GOV-STRATUM-SEAM-1 P1)

- `policy_bundle(workflow=None, domain=None, statuses=("active",))` calls
  `GET /memory/policy/bundle`, encoding `status` as a repeatable query key.
- `record_enforcement_event(event)` posts the contract event unchanged to
  `POST /memory/policy/events` and returns its idempotency result.

### Added — `import_chat_export()` / `chat_export_formats()` (DIST-CHAT-IMPORT-1)

Upload a ChatGPT or Claude conversation export and have it ingested through the normal
conversation pipeline. `import_chat_export(export_bytes, source_format="auto",
max_conversations=25)` sniffs the zip magic bytes to label the upload correctly and returns
`{source_format, conversations_imported, conversations_failed, turns_imported,
items_created, warnings}`.

**Read `warnings`.** A non-empty list means something was capped, skipped, or degraded even
though the call returned 200 — the import is synchronous and capped by default, so a
partial import is a normal outcome, not an error.


### Changed — recommended wake-up budget ~200 -> ~300 (CORE-TOKEN-ESTIMATOR-UNDERCOUNT-1)

- `recall_pack(preset="wakeup")` docstring and example updated. The card is
  content-bounded (~70 real tokens); the headroom is for verbose workspaces.

### Added — `recall_pack(preset=...)` (CORE-RECALL-BUDGET-1 Phase 5)

- `client.recall_pack(200, preset="wakeup")` returns the L1 session-start card. Omitted
  when not supplied, so the wire body still matches the JS SDK and the MCP remote backend.

### Added — CORE-RECALL-BUDGET-1: recall_pack client surface

- `recall_pack(budget_tokens, query=None, sections=None)` →
  `POST /memory/recall/pack`. Assembles one priority-ordered context block
  within a token budget from the default sections (active plan, anchors,
  latest snapshot, tier-1/tier-2 memory items, notes), or a caller-supplied
  `sections` override (`{"name", "cap_tokens"}`). Returns the RecallPack dict
  (`{"block", "manifest": {budget_tokens, used_tokens, tokenizer, query,
  sections}}`). `query`/`sections` are omitted from the request body when
  `None`.

### Added — CORE-MEMTYPE-DECLARE-1 P4: record lifecycle client surface

- `migrate_ontology_type_instances(..., on_violation="refuse"|"skip")`
  supports record schema preflight/skip behavior and returns the additive
  record migration report fields. The default is omitted on the wire so
  existing entity migration requests remain byte-compatible.
- `retire_ontology_type(type_id, reason)` retires this workspace's OWN confirmed
  record class. The server refuses with 400 unless the type resolves to the
  private layer and is kind `"record"` — public and pack classes are shared
  vocabulary and are not retirable through this route.

### Added — CORE-MEMTYPE-DECLARE-1 P1: declare surface

- `declare_type(name, kind=..., properties_schema=..., required_properties=...,
  storage_strategy=..., storage_searchable=..., tier=...)` →
  `POST /memory/ontology/types`. `kind="record"` declares a concrete record
  type; items with `memory_type=name` are then accepted by `add()` and
  `ingest_structured()` with schema checks (STRICT by default — violations
  refused with a structured 400; server-side literal-`false` env kill-switch
  downgrades to WARNING).
- `declare_relation(name, domain=..., range=..., cardinality=..., ...)` →
  `POST /memory/ontology/relations` (declare-only in P1).
- `list_ontology_types()` gains the `kind` filter.

## [1.4.60] - 2026-08-06

### Added (2026-08-05) — SVC-ALLOC-1 sequence client surface

- New `allocate_sequence(name, floor=None, count=None)` and
  `peek_sequence(name)` for workspace-scoped monotonic allocation.
- `allocate_sequence` raises on **every** non-2xx and never returns a sentinel.
  Unlike the lease there is no benign failure: returning `None` on a 503 would
  let a caller mistake coordinator failure for a value.
- `peek_sequence` returns `None` only for a 404 (never allocated). A 503 raises
  — a down coordinator is not the same answer as "does not exist".
- `floor=0` is sent rather than dropped; it is falsy but meaningful.

### Added (2026-08-05) — embed control + supersede-link (SVC-EMBED-CONTROL-1, SVC-SUPERSEDE-LINK-1)

- `add()` accepts `embed=True|False|None`. Sent only when set, so an omitted
  argument is byte-identical to the previous request. Valid only with
  `use_pipeline=False`; the service answers 400 for the combination.
- New `supersede_link(item_id, new_item_id, reason=None)` relates two records
  that already exist. Raises `SmartMemoryNotFoundError` on 404 (missing and
  out-of-scope are deliberately indistinguishable) and
  `SmartMemoryValidationError` on 400 self-link / 409 store refusal.

### Added (2026-08-05) — SVC-LEASE-1 lease client surface

- New `acquire_lease()`, `renew_lease()`, and `release_lease()` methods for
  scoped renewable leases.
- Only recognised ownership conflicts return normal control-flow values (`None`
  or `False`); validation, quota, coordinator, malformed-response, and network
  failures raise so callers never treat an unknown outcome as a known conflict.
  A 409 is control flow only when its `detail.reason` is the one the call models.
- **Deliberate divergence from the `get`/`update`/`delete` convention** in
  `.claude/rules/error-coverage.md`, which removed sentinel returns in 0.6.0:
  `release_lease()` returns `False` rather than raising when the token no longer
  owns the lease. Release is normally called from a `finally` block, where an
  exception would mask the error that ended the critical section. The 0.6.0
  change targeted blanket `except Exception` swallowing that hid 404/403/500
  from callers; these methods do the opposite — they recognise exactly one
  status-and-reason pair and re-raise everything else.

### Added (2026-08-05) — `include_retracted` on `search()` (CORE-RETRACTED-RECALL-1)

- `search()` gains `include_retracted: bool = False`, sent only when true (per the
  contract's SDK rule: omit unset optional params rather than serializing null).
- Sibling of `include_superseded`, not covered by it — a retraction has no
  replacement. **Retracted items are hidden by default as of this release**; pass
  `include_retracted=True` to see them.

## [1.4.59] - 2026-08-04

### Added (2026-08-04) — as-of search + explain (PLAT-AUDITABLE-MEMORY-1 T11)
- `search()` gains `as_of_date` (ISO string or datetime, serialized to ISO)
  and `include_superseded` — transaction-time travel per the search contract.
- New `explain(memory_id)`: the single-call audit answer (explain-contract
  shape). Raises `SmartMemoryNotFoundError` on 404. `chain_verified` of
  `None` means nothing to verify, not a tamper warning.
- Contract tests pin the search body field names and the ExplainResponse
  top-level blocks against `explain-contract.json`; typed 404/400/500 error
  coverage per house rule.

## [1.4.57] - 2026-08-02
Version copied verbatim from `smart-memory-core/VERSION` per the release sync chain — core is the
only dial. The client had been lagging at 1.4.53 while core advanced to 1.4.57; this release
resynchronises it. The client declares no `smartmemory-core` dependency, so there is no pin to
update. Published wheel-only.

### Added (2026-08-02) — GRAPH-API-1l: `list_memories()`
- New `list_memories(limit=50, offset=0, order="asc", metadata_key=None, metadata_value=None)`
  wrapping `GET /memory/list`. The client had **no** wrapper for this endpoint at all before
  now, so this is a new method rather than an added parameter.
- Optional `metadata_key` / `metadata_value` filter to an exact metadata match. Nested keys use
  dot syntax (`"profile.tier"`) and are sent unchanged — translation to the flattened storage
  separator is the server's job. Returns `{"items", "total", "limit", "offset"}`, where `total`
  counts the filtered set and so drives pagination directly.
- Filter params are omitted from the query string entirely when unset: the route validates them
  as a both-or-neither pair, so sending one as an explicit `None` would be a 422.

### Deprecated (2026-08-02) — GRAPH-API-1l: `search_by_metadata()`
- Docstring-level deprecation pointing at `list_memories()`. **No behaviour change and no
  `DeprecationWarning`** — the two endpoints return slightly different item shapes, so this is a
  signal to migrate deliberately, not a mechanical find-and-replace.

### Changed (2026-08-02) — GRAPH-API-1i wire surface added, then removed same day
- `add()` briefly gained a `retrieved_context_ids` parameter, an item-lift, and a body
  field, and the `MemoryItem` model briefly carried the field. All removed after review:
  metadata is the storage substrate — a `metadata["retrieved_context_ids"]` write crosses
  the wire, persists, and lifts back onto the server-side typed field, and the only
  consumer (`context_retention`) reads the metadata copy in-process. The dedicated wire
  surface duplicated that path and was never needed. Provenance continues to travel in
  `metadata`; net change to this SDK versus the last release: none.

### Added (2026-08-02) — MAYA-SAID-1
- search_by_metadata gains limit param (route already supported it)

### Added (2026-08-01) — GRAPH-API-1b: graph + decision route wrappers
- New methods for routes that existed server-side but had no SDK surface:
  `get_edges_bulk`, `bulk_graph_upsert`, `get_graph_path`, `get_graph_full`,
  `contradict_decision`, `get_decision_conflicts`, `search_decisions`.

### Changed (auto, lockstep) — track product version 1.4.51 (1.4.51)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.50 (1.4.50)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.49 (1.4.49)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.48 (1.4.48)
- Version copied from the smartmemory-core release (single-source lockstep).

### Added (2026-07-13) — MAYA-SELF-1 system teams and supersession
- `create_team()` accepts additive `is_system=True`, while `list_teams()` exposes hidden machine-owned
  workspaces only when `include_system=True`; both defaults preserve existing request shapes.
- `supersede()` appends a replacement through `POST /memory/{item_id}/supersede` while retaining the
  predecessor's history.

### Changed (auto, lockstep) — track product version 1.4.47 (1.4.47)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.46 (1.4.46)
- Version copied from the smartmemory-core release (single-source lockstep).

### Fixed (2026-07-12) — MAYA-ENVISION-1: cross-package add() fidelity
- **`add()` duck-types MemoryItem-likes**: smartmemory-core's `MemoryItem` is a different
  class from the SDK's, so the strict isinstance check silently stored `str(item)` (the
  repr) as `semantic` content with all metadata dropped. Any object with `.content` is now
  treated as a memory item; the true fallback branch logs WARNING.
- **`conversation_context` datetime serialization**: `dataclasses.asdict` left
  `created_at`/`last_updated_at` as datetime objects, failing JSON encoding on every
  `add(conversation_context=...)` call with core's `ConversationContext`. Now prefers the
  object's own `to_dict()` and normalizes datetimes in the dataclass fallback.

### Added (2026-07-12) — archive client methods (MAYA-ENVISION-1)
- `SmartMemoryClient.archive_put()` and `archive_get()` now cover the archive store and
  retrieval routes used by archive-first conversation ingestion.

### Changed (auto, lockstep) — track product version 1.4.45 (1.4.45)
- Version copied from the smartmemory-core release (single-source lockstep).

### Added (2026-07-09) — ONTO-HITL-CURATE-1 SDK wrappers
- `SmartMemoryClient` gains wrappers for the ontology curation queue HTTP surface:
  `list_ontology_review_queue`, `approve_ontology_type`, `reject_ontology_type`,
  `merge_ontology_review_type`, `edit_promote_ontology_type`, `assign_ontology_review`,
  `bulk_ontology_review_action`.
- Tests in `tests/test_ontology_curate_methods.py` cover exact queue URLs, params, bodies,
  URL-encoded type ids, bulk mixed reports, and 404/409/400 typed-exception mapping.

### Added (2026-07-09) — ontology type/relation read, audit, and migration methods (ONTO-CRUD-1)
- `SmartMemoryClient` gains 9 typed wrappers over the `ontology_crud.py` HTTP surface:
  `list_ontology_types`, `list_ontology_relations`, `get_ontology_type`, `get_ontology_relation`,
  `list_ontology_audit`, `get_ontology_type_audit`, `get_ontology_relation_audit`,
  `get_ontology_pack_audit`, `migrate_ontology_type_instances`.
- Tests in `tests/test_ontology_crud_methods.py` cover the happy path for all 9 methods plus
  404/400/500 typed-exception cases.

### Changed (auto, lockstep) — track product version 1.4.44 (1.4.44)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.44 (1.4.44)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.43 (1.4.43)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.42 (1.4.42)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.40 (1.4.40)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.39 (1.4.39)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.38 (1.4.38)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.37 (1.4.37)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (2026-07-03) — persistent httpx.Client for connection reuse
- **`SmartMemoryClient` now holds one `httpx.Client` (`self._client`)** for keep-alive
  connection pooling across its many per-method calls, replacing per-call module-level
  `httpx.request` / `httpx.get`. Added `close()`, and the context-manager `__exit__`
  (previously a `pass` stub) + `__del__` now close the pool.
- **`verify_ssl` is now actually honored.** The old module-level calls never passed `verify=`,
  so the constructor arg was dead config; it now reaches the pooled client.
- **Test mock target moved** from `smartmemory_client.client.httpx.request` to
  `httpx.Client.request` across all 19 mocking test files (201 patch sites). Positional
  `call_args[0]` assertions are unaffected: the patched class method is a non-descriptor
  MagicMock, so no `self` is injected into the recorded args.
- New `tests/test_client_lifecycle.py` (pool identity, verify_ssl wiring, pooled-call routing,
  idempotent close, context-manager teardown). CI tier: 288 passed.

### Added (2026-07-02) — URL contract coverage
- Added `tests/test_url_contracts.py`, a table-driven pytest module that mocks
  the SDK transport and asserts exact verb/path contracts for the main public
  memory CRUD, search, ingest, decision, code, plan, reasoning trace, and
  summary snapshot client methods against the service route surface.

### Changed (auto, lockstep) — track product version 1.4.36 (1.4.36)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (lockstep) — track smartmemory-core==1.4.33 (1.4.33)
- Version copied from smartmemory-core 1.4.33 release (single-source lockstep; no client code change). Core delivers CORE-RELATION-RULER-1 (EntityRuler cold-start seed ROM).

### Added (CORE-LLM-GEMINI-1) — Gemini provider key
- `update_llm_keys()` gains a `gemini_key` parameter and sends `gemini_key` in the
  `PATCH /auth/llm-keys` body, mirroring openai/anthropic/groq. Body assertion updated +
  new `gemini_key` round-trip assertion in `tests/test_client_full_coverage.py` (15/15).

### Added (ONTO-HITL-CONSUMER-1) — ontology HITL queue methods
- `list_ontology_hitl(status='open', kind=None, limit=50)` → `GET /memory/ontology/hitl`
  (`kind` omitted when None). `resolve_ontology_hitl(item_id, action, note=None)` →
  `POST /memory/ontology/hitl/{id}/resolve`. 404 → `SmartMemoryNotFoundError` (missing/cross-tenant),
  422 → `SmartMemoryValidationError`. Tests: `tests/test_ontology_hitl_methods.py` (7/7). Codex review clean.

### Changed (auto, lockstep) — track product version 1.4.32 (1.4.32)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.28 (1.4.28)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.27 (1.4.27)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.26 (1.4.26)
- Version copied from the smartmemory-core release (single-source lockstep).

### Changed (auto, lockstep) — track product version 1.4.25 (1.4.25)
- Version copied from the smartmemory-core release (single-source lockstep).


### Deprecated (SEC-AUTH-REVOCATION-1 token-prefix, 2026-06-04) — raw-JWT api_key (0.7.8)

- **`SmartMemoryClient(api_key="eyJ…")` now emits a `DeprecationWarning`.** A raw JWT in the
  `api_key` slot (or `SMARTMEMORY_API_KEY`) is not scoped or revocable per-key. Mint a proper key
  via `POST /memory/api-keys` and use the new `sm_live_…` / `sm_test_…` prefixes (legacy `sk_…`
  still works). Properly-prefixed keys emit no warning. Fixed a latent `import warnings` shadowing
  in `__init__` surfaced by this change.

### Added (CORE-GRAPH-CANONICAL-DEDUP-1, 2026-06-03) — `dedup_entities()` (0.7.7)

- **`client.dedup_entities(dry_run=False, require_structural_confirmation=True)`** — POSTs
  `/memory/graph/dedup-entities` (both flags as query params). Opt-in graph-maintenance op that collapses
  same-name cross-extractor entity-node fragments into one node, unblocking ensemble alias disambiguation.
  Returns `merged_clusters / merged_nodes / redirected_edges / abstained_clusters / dry_run / workspace_id /
  user_id`. Contract:
  `smart-memory-docs/docs/features/CORE-GRAPH-CANONICAL-DEDUP-1/dedup-entities-contract.json`.

### Added (CORE-GRAPH-ALIAS-DISAMBIG-1, 2026-06-03) — `resolve_aliases(disambiguate=...)` (0.7.6)

- **`client.resolve_aliases(dry_run=False, disambiguate=False)`** threads the new opt-in collision-
  disambiguation flag (default off) as a query param; response gains `disambiguated`. Contract:
  `docs/features/CORE-GRAPH-ALIAS-DISAMBIG-1/disambiguate-contract.json`.

### Added (CORE-GRAPH-ALIAS-RESOLVE-2, 2026-06-02) — `resolve_aliases(dry_run=...)`

- **`client.resolve_aliases(dry_run=False)`** wraps `POST /memory/graph/resolve-aliases`.
  Merges unambiguous single-token entity aliases ("Hudson") into their multi-token
  canonical ("Rock Hudson") over the caller's workspace graph, abstaining on collisions.
  `dry_run` is sent as a **query parameter** (mirrors `cluster()` / the `/clustering/run`
  precedent), not a JSON body. Returns the parsed report dict: `resolved`, `abstained`,
  `redirected_edges`, `ambiguous`, `dry_run`, `workspace_id`, `user_id`.
- Tests: `tests/integration/test_graph_operations.py::TestResolveAliases` (real-service
  dry-run + default call; auto-skip when the service is unavailable).
  Contract: `smart-memory-docs/docs/features/CORE-GRAPH-ALIAS-RESOLVE-2/resolve-aliases-contract.json`.

### Added (NEURO-1d, 2026-06-02) — `search(consolidation_first=...)` + `include_consolidated=...`

- **`client.search(..., consolidation_first=True)`** surfaces a consolidated summary above the
  scattered source memories it consolidates — best for synthesis queries ("what is known about X?").
  Opt-in; implies `include_consolidated`. **`include_consolidated=True`** includes consolidated
  source memories (normally hidden). Both default off → request body omits the keys, so existing
  callers are byte-identical on the wire.
- Tests: `tests/test_client.py::TestSearchConsolidationParams` (body serialization + default-omit).
  Contract: `smart-memory-docs/docs/features/CORE-SEARCH-1/search-contract.json`.

### Added (CORE-AGENT-2, 2026-05-24) — `get_evaluation()` + `list_evaluation_history()`

- **`client.get_evaluation(agent_id, dimension, domain)`** — wraps `GET /memory/agents/{agent_id}/evaluation`. Returns `dict | None`; cold-start (no evaluation written yet) returns `None` cleanly per the contract (`200 {evaluation: null}` from the service). Raises `SmartMemoryNotFoundError` (404) for cross-tenant / unknown agent.
- **`client.list_evaluation_history(agent_id, dimension, domain, limit=...)`** — wraps `GET /memory/agents/{agent_id}/evaluation/history`. Returns a list of historical evaluation rows in supersession order.
- 8 new tests in `tests/test_client_evaluation.py` (happy / 404 / cold-start / pagination).

Source: `smart-memory-docs/docs/features/CORE-AGENT-2/report.md`. Contract: `smart-memory-docs/docs/features/CORE-AGENT-2/evaluation-contract.json`.

### Added (CORE-DECISION-PROVENANCE-LOOKUP-1, 2026-05-23) — `list_decisions(provenance_memory_id=...)`

- **`list_decisions()`** gains an optional `provenance_memory_id` kwarg. When set, the SDK passes it through to `GET /memory/decisions?provenance_memory_id=<id>` and returns only active decisions whose provenance subgraph contains that memory. Other filters (`domain`, `decision_type`, `min_confidence`, `limit`) compose in-query — the SDK never sees a truncated-below-limit result. Backwards-compatible; existing callers see no behavior change.


### Changed (CORE-RECALL-LINEAGE-1 Phase 3, 2026-05-22) — SearchResponse envelope unwrap

- **`SmartMemoryClient.search()`** now always unwraps the `{results, group_roots, citations?}` envelope. Callers continue to receive `List[MemoryItem]` — no signature change. The envelope siblings are exposed on the client instance:
  - `client.last_group_roots: Dict[str, GroupRootStub]` — canonicals that didn't match the query, keyed by root_id. Each stub: `{item_id, accessible, content_preview?, memory_type?, origin?}`.
  - `client.last_citations: List[Citation]` — unchanged from RECALL-CITATIONS-1; now sourced from the envelope sibling instead of the legacy double-wrap.
- **`MemoryItem`** dataclass gains `origin: Optional[str]` and `lineage_roots: List[str]`. `from_dict` reads both. Backwards-compatible with old (pre-envelope) responses — missing keys default to `None` / `[]`.
- Pre-envelope service responses (bare list) still parse correctly during rollout — the client tolerates both shapes.

### Added (RECALL-CITATIONS-1, 2026-05-10)

- **`SmartMemoryClient.search(cite=True)`** opts into the citation-ready response. The wire response is `{results, citations}`; the client unwraps `results` (callers continue to receive `List[MemoryItem]`) and exposes the citation array via the new `client.last_citations` property. Each citation has shape `{n, item_id, item_type, preview, score, footnote_marker}` per the RECALL-CITATIONS-1 contract. `last_citations` is `[]` when `cite=False` or when there are no results.

### Changed (CORE-EXPERTISE-1 Phase 4b, 2026-05-08)

- **README gains "Expertise Layer" API section.** Shows `client.create_decision(..., rejected_alternatives=, rationale=, constraints=)` for capture and `client.search(query, expertise=True)` returning the typed dict for recall. Links to the canonical 1-pager. No code change.

### Added (CORE-EXPERTISE-1 Phase 4a, 2026-05-08)

- **`SmartMemoryClient.search(..., expertise=False)` parameter added.** When `True`, returns `Dict[str, List[MemoryItem]]` keyed by expertise type (decision/constraint/learned/opinion/reasoning/observation), each bucket capped at `top_k`. Default returns `List[MemoryItem]` — no breaking change. Forwarded as `expertise: true` in the POST body; response parsing branches on the flag (parses `{results: {<bucket>: [...]}}`). Contract: `smart-memory-docs/docs/features/CORE-EXPERTISE-1/expertise-search-contract.json`.

### Added (CORE-EXPERTISE-1 Phase 1, 2026-05-07)

- **`SmartMemoryClient.create_decision()` accepts `rejected_alternatives`, `rationale`, `constraints`.** Three new optional kwargs forwarded to `POST /memory/decisions/create` as snake_case payload keys; omitted entirely when unset (no `null`-leakage). 2 new contract tests in `tests/test_decision_methods.py`. Feature folder: `smart-memory-docs/docs/features/CORE-EXPERTISE-1/phase-1-decision-schema/`.

## [0.7.0] — 2026-05-04

### Changed

- **Track core 0.9.0 release.** Tier 1 + Tier 2 audit-half work in core (ONTO-RECONCILE-1 Phase 4) ships under core 0.9.0. The HTTP API surface this client targets is unchanged, so the SDK itself ships no behavior changes for this release — bump establishes a tracking version pair for the new core baseline.

### Changed — BREAKING (SDK-CONSISTENCY-1)

- **`client.get(item_id)` now raises instead of returning `None`.** Returns `MemoryItem` on success. Raises `SmartMemoryNotFoundError` (404), `SmartMemoryPermissionError` (401/403), `SmartMemoryServerError` (5xx), or `SmartMemoryClientError` (transport/other). Callers that relied on `if not (item := client.get(id)): ...` must switch to `try/except SmartMemoryNotFoundError`.
- **`client.update(...)` now raises instead of returning `False`.** Return type is now `None`. Same typed exceptions as `get()` (plus `SmartMemoryValidationError` on 400/422).
- **`client.delete(item_id)` now raises instead of returning `False`.** Return type is now `None`. Same typed exceptions as `get()`.
- **`client.provide_feedback()` deleted.** It targeted a server endpoint shape that has been removed (the legacy `/memory/feedback` route accepting `{feedback, memory_type}`). The `client.feedback(item_ids, outcome, query)` method is the correct path for retrieval reinforcement.

### Added (SDK-CONSISTENCY-1)

- **Typed exception hierarchy** as siblings of `SmartMemoryClientError`:
  - `SmartMemoryNotFoundError` (404)
  - `SmartMemoryPermissionError` (401/403)
  - `SmartMemoryValidationError` (400/409/422)
  - `SmartMemoryServerError` (5xx)
  All inherit from `SmartMemoryClientError` for backwards compatibility — existing `pytest.raises(SmartMemoryClientError)` and `match="Request failed"` assertions still pass. Each exception exposes `status_code` and `detail` attributes.
- **`client.add(..., profile_name=None)`** parameter added to bring Python parity with the JS SDK's `MemoryAPI.create({ profileName })`. Routes to `profile_name` server-side; selects an alternate pipeline configuration. Omitted from the request body when `None`.

### Fixed

- **PUT→PATCH stale assertions:** `test_client_full_coverage.py` was asserting `PUT` on `/auth/llm-keys`, `/memory/teams/{id}`, and `/memory/teams/{id}/members/{user_id}`. The SDK methods themselves had already migrated to `PATCH` in `06d7f82`; only the test mock-call assertions were stale. Updated.

### Added

- **CORE-SUMMARY-1: Memory snapshot SDK methods.** Six new methods on `SmartMemoryClient`: `summary_generate(window_start=None, include_markdown=True)`, `summary_latest()`, `summary_get(snapshot_id)`, `summary_list(is_heartbeat=None, limit=20, before=None)`, `summary_delta(from_snapshot_id, to_snapshot_id)`, `summary_delete(snapshot_id)`. Read methods return `None` on 404; write methods raise `SmartMemoryClientError`. Tests cover happy path + 404 + 4xx + 500 per the global error-coverage rule. Contract: [`smart-memory-docs/docs/features/CORE-SUMMARY-1/snapshot-contract.json`](../smart-memory-docs/docs/features/CORE-SUMMARY-1/snapshot-contract.json).

- **CORE-CRUD-UPDATE-1: `client.update()` exposes `properties` and `write_mode`.** Signature extended: `client.update(item_id, content=None, metadata=None, properties=None, write_mode=None)`. The convenience pair (`content`/`metadata`) still works — when omitted, no behavior change. Pass `properties={...}` for direct node-property updates; `properties` takes precedence over the conveniences when both are provided. `write_mode="merge"|"replace"` controls write semantics; default merges. Returns True on success, False on any HTTP error (unchanged). Contract: `smart-memory-docs/docs/features/CORE-CRUD-UPDATE-1/update-contract.json`.

### Changed — BREAKING

- **CORE-MEMORY-DYNAMICS-1 M1b (fixup 2026-04-20):** golden CRUD integration test (`tests/integration/test_crud_golden.py::test_add_different_memory_types`) parametrize list updated from `[..., "working"]` to `[..., "pending"]`. Client callers that hardcode `memory_type="working"` will now receive a `400` validation error from the server post-M1b rename. Commit `3ca985f`.

### Added

- **CORE-MEMORY-DYNAMICS-1 M1a: `SmartMemoryClient.get_working_context(session_id, query, k=20, max_tokens=None, strategy=None) → Dict[str, Any]`.** New method posting to `POST /memory/context` via the shared `_request` helper. Returns contract-shaped response per `smart-memory-docs/docs/features/CORE-MEMORY-DYNAMICS-1/context-api-contract.json` (keys: `decision_id`, `items`, `drift_warnings`, `strategy_used`, `tokens_used`, `tokens_budget`, `deprecation`). Optional params filtered by `is not None` (not truthiness) so `max_tokens=0` and `strategy=""` are sent to the server for validation — protects against truthiness-filter regressions. Server `400 budget_too_small` and `5xx` failures raise `SmartMemoryClientError` per existing SDK error convention. 8 unit tests covering happy path, auth+workspace header emission, optional-param encoding, falsy-but-valid values, and 400/500 error paths. No `memory_recall` shim on this SDK — the SDK never exposed `memory_recall`.

### Changed

#### Header Rename: X-Team-Id → X-Workspace-Id (SCOPE-WS-1)
- Constructor now accepts `workspace_id` parameter (preferred); `team_id` kept as deprecated alias
- `team_id` emits `DeprecationWarning` only when used as the actual fallback (not when `workspace_id` is also provided)
- Both `team_id` and `workspace_id` deprecated env vars (`SMARTMEMORY_TEAM_ID`) remain supported; `SMARTMEMORY_WORKSPACE_ID` is new preferred env var
- `X-Team-Id` request header replaced with `X-Workspace-Id` in all HTTP calls
- `team_id` alias and `SMARTMEMORY_TEAM_ID` env var will be removed in v0.5.0

### Added
- **Procedure Schema Drift Detection (CFS-4)**: 5 new methods for schema drift management
  - `list_drift_events()` — list drift events with filtering (procedure_id, resolved, breaking_only, date range)
  - `get_drift_event(event_id)` — get drift event detail with full changes list
  - `resolve_drift_event(event_id, note)` — mark a drift event as resolved
  - `sweep_drift()` — trigger workspace-wide drift sweep
  - `list_schema_snapshots(procedure_id)` — list schema snapshot history
- **Drift detection tests** (`tests/test_procedure_drift.py`): 16 tests covering all 5 endpoints with happy path, error codes, parameter filtering
- **Error handling tests** (`tests/test_client_errors.py`): 21 tests covering HTTP error codes (400, 401, 403, 404, 422, 500), connection errors, timeouts, success responses, and request argument forwarding

### Fixed
- **Package structure**: Created missing `models/__init__.py` for proper model exports
- **Module exports**: Fixed `__init__.py` to properly export `MemoryItem` and `ConversationContextModel`
- **Version detection**: Use `importlib.metadata` for installed package version with fallback to VERSION file
- **Test assertions**: Fixed API path assertions to match actual client implementation

### Added

#### Usage Methods
- `get_usage_limits()` - Get quota limits for current subscription tier
- `get_current_usage()` - Get current usage statistics
- `get_available_tiers()` - Get available subscription tiers

#### Reasoning Traces (System 2 Memory)
- `extract_reasoning()` - Extract reasoning traces from content
- `store_reasoning_trace()` - Store reasoning trace with artifact links
- `query_reasoning()` - Query reasoning traces ("why" queries)
- `get_reasoning_trace()` - Get specific reasoning trace by ID

#### Synthesis Evolution
- `synthesize_opinions()` - Form opinions from episodic patterns
- `synthesize_observations()` - Create entity summaries from facts
- `reinforce_opinions()` - Update opinion confidence based on evidence

---

## [0.2.6] - 2025-11-25

### 🎯 Interface Alignment with Core Library

Aligned client method names and return types with core `smartmemory` library for portable code.

### Added
- **New API methods** for complete service coverage:
  - `add_edge()` - Direct edge creation between nodes with custom properties
  - `reflect()` - Memory pattern analysis and insights
  - `summarize()` - High-level memory content summary

### Changed
- **Method renames** to match core library:
  - `get_summary()` → `summary()`
  - `get_orphaned_notes()` → `orphaned_notes()`
  - `summarize_memories()` → `summarize()`
  - `prune_memories()` → `prune()`
- **MemoryItem** enhanced with:
  - `from_dict()` factory method for consistent parsing
  - Dict-like access (`item["content"]`) for compatibility
  - Additional fields: `user_id`, `workspace_id`, `tenant_id`, `tags`
- **Return types**: `get()` and `search()` now use `MemoryItem.from_dict()` for consistent parsing
- **Fixed** `get_neighbors()` to use standard `_request()` helper

### Removed
- Deleted stale work artifacts: `CLEANUP_CHECKLIST.md`, `PACKAGE_SETUP_COMPLETE.md`, `SSG_UPDATE.md`
- Removed duplicate methods in Usage section

---

## [0.1.17] - 2025-11-23

### Added
- **SSG (Similarity Graph Traversal) support** for enhanced semantic retrieval
  - New `search_advanced()` method with `query_traversal` and `triangulation_fulldim` algorithms
  - Optional `use_ssg` parameter in `search()` method for better multi-hop reasoning
  - Superior retrieval quality: 100% test pass rate, 0.91 precision/recall (vs 0.88 basic)
  - Reference: Eric Lester. (2025). Novel Semantic Similarity Graph Traversal Algorithms for Semantic Retrieval Augmented Generation Systems.
- Initial client implementation
- Full API coverage for SmartMemory Service
- JWT authentication support
- Type-safe Pydantic models
- Comprehensive error handling
- Comprehensive documentation
- Example usage for Maya and Studio integration
- Sync script for updating from service repository
- GitHub Actions workflows for testing and publishing

### Features
- ✅ Type-safe API with Pydantic models
- ✅ Automatic JWT authentication
- ✅ Full API coverage
- ✅ Comprehensive error handling
- ✅ Environment variable support
- ✅ Context manager support
- ✅ Detailed logging

### Documentation
- Complete README with examples
- API reference
- Authentication guide
- Integration examples
- Development guide

[1.0.0]: https://github.com/smartmemory/smart-memory-client/releases/tag/v1.0.0
