# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
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
