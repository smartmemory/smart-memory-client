"""
SmartMemory HTTP Client

A clean, manually-maintained HTTP client for the SmartMemory Service API.

Features:
- JWT authentication with automatic token handling
- Type-safe operations with Pydantic models
- Comprehensive error handling
- Full API coverage (CRUD, search, ingestion, links, etc.)

For more information, see: https://github.com/smartmemory/smart-memory-client
"""

import logging
import os
import warnings
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

import httpx

# Use local model instead of core dependency
from smartmemory_client.models.memory_item import MemoryItem
from smartmemory_client.models.conversation import ConversationContextModel

logger = logging.getLogger(__name__)


class SmartMemoryClientError(Exception):
    """Base exception for SmartMemory client errors.

    Subclasses (raised by the SDK on HTTP-status errors) expose:
        status_code (int | None): the HTTP status the server returned, if any.
        detail (str): the response body (best-effort).

    Catching ``SmartMemoryClientError`` continues to handle every typed
    subclass for backwards compatibility.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or ""


class SmartMemoryNotFoundError(SmartMemoryClientError):
    """Raised on HTTP 404 — the requested resource does not exist."""


class SmartMemoryPermissionError(SmartMemoryClientError):
    """Raised on HTTP 401/403 — auth missing, expired, or insufficient."""


class SmartMemoryValidationError(SmartMemoryClientError):
    """Raised on HTTP 400/409/422 — request shape or state was rejected."""


class SmartMemoryServerError(SmartMemoryClientError):
    """Raised on HTTP 5xx — the server failed to process the request."""


def _exception_for_status(status: int) -> type[SmartMemoryClientError]:
    """Map an HTTP status code to the most specific SDK exception class."""
    if status == 404:
        return SmartMemoryNotFoundError
    if status in (401, 403):
        return SmartMemoryPermissionError
    if status in (400, 409, 422):
        return SmartMemoryValidationError
    if 500 <= status < 600:
        return SmartMemoryServerError
    return SmartMemoryClientError


class SmartMemoryClient:
    """
    SmartMemory HTTP Client

    A clean, manually-maintained HTTP client for the SmartMemory Service API.

    Features:
    - JWT authentication with automatic token handling
    - API key authentication for automation/scripts
    - Type-safe operations with Pydantic models
    - Comprehensive error handling
    - Full API coverage

    Usage:
        ```python
        from smartmemory_client import SmartMemoryClient

        # With API key (for automation/scripts)
        client = SmartMemoryClient(
            base_url="http://localhost:9001",
            api_key="sk_your_api_key"
        )

        # With JWT token (if you already have one)
        client = SmartMemoryClient(
            base_url="http://localhost:9001",
            token="eyJ..."
        )

        # With login (interactive flow)
        client = SmartMemoryClient(base_url="http://localhost:9001")
        client.login(email="user@example.com", password="secret")

        # Add memory
        item_id = client.add("This is a test memory")

        # Search
        results = client.search("test", top_k=5)

        # Ingest with full pipeline
        result = client.ingest(
            content="Complex content",
            extractor_name="llm",
            context={"key": "value"}
        )
        ```
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
        verify_ssl: bool = True,
        workspace_id: Optional[str] = None,
        team_id: Optional[
            str
        ] = None,  # deprecated alias for workspace_id, removed in v0.5.0
    ):
        """
        Initialize SmartMemory client wrapper.

        Args:
            base_url: Base URL of the SmartMemory service
            api_key: API key (sk_...) for automation (or set SMARTMEMORY_API_KEY env var)
            token: JWT token for authentication (or set SMARTMEMORY_TOKEN env var)
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            workspace_id: Workspace ID for multi-tenant isolation (preferred)
            team_id: Deprecated alias for workspace_id. Removed in v0.5.0.

        Note:
            Provide either api_key OR token, not both. If neither provided,
            use login() method to authenticate.
        """
        # Determine base URL from parameter or environment
        if base_url is None:
            host = os.getenv("SMARTMEMORY_CLIENT_HOST") or os.getenv(
                "SMARTMEMORY_SERVER_HOST", "localhost"
            )
            if host in ("0.0.0.0", "::"):
                host = "localhost"
            try:
                port = int(os.getenv("SMARTMEMORY_SERVER_PORT", "9001"))
            except Exception:
                port = 9001
            base_url = f"http://{host}:{port}"

        self.base_url = base_url
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        # Persistent HTTP client for connection reuse (keep-alive pooling) across
        # the many per-method calls this SDK makes. Also the single place
        # verify_ssl is actually honored — the previous module-level httpx.request
        # / httpx.get calls never passed verify=, so verify_ssl was dead config.
        self._client = httpx.Client(verify=verify_ssl, timeout=timeout)

        # Store tokens separately for clarity
        self._api_key: Optional[str] = None
        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None

        # Resolve auth from parameters or environment
        # Priority: explicit param > env var
        resolved_api_key = api_key or os.getenv("SMARTMEMORY_API_KEY")
        resolved_token = token or os.getenv("SMARTMEMORY_TOKEN")

        # Use token if provided, otherwise api_key
        if resolved_token:
            self._token = resolved_token
            logger.info(f"Using JWT token (length: {len(resolved_token)})")
        elif resolved_api_key:
            self._api_key = resolved_api_key
            # SEC-AUTH-REVOCATION-1: a raw JWT in SMARTMEMORY_API_KEY is not scoped
            # or revocable per-key. Steer callers to minted sm_live_/sm_test_ keys.
            if resolved_api_key.startswith("eyJ"):
                warnings.warn(
                    "SMARTMEMORY_API_KEY appears to be a raw JWT. JWTs are not "
                    "scoped or revocable per-key. Mint an API key via "
                    "POST /memory/api-keys and use sm_live_/sm_test_ prefixed keys.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            logger.info(f"Using API key: {resolved_api_key[:10]}...")
        else:
            logger.warning("No auth credentials provided. Use login() to authenticate.")

        # Resolve workspace_id; team_id is a deprecated alias (removed in v0.5.0).
        # Warn only when team_id is actually used as the fallback (workspace_id not provided).
        self.team_id = (
            workspace_id
            or team_id
            or os.getenv("SMARTMEMORY_WORKSPACE_ID")
            or os.getenv("SMARTMEMORY_TEAM_ID")
            or "team_default_demo"
        )
        if team_id is not None and not workspace_id:
            warnings.warn(
                "The 'team_id' parameter is deprecated and will be removed in v0.5.0. "
                "Use 'workspace_id' instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Build default headers (auth header added dynamically)
        self._base_headers = {
            "Content-Type": "application/json",
            "X-Workspace-Id": self.team_id,
        }

        if self.is_authenticated:
            logger.info(
                f"SmartMemoryClient initialized with authentication. "
                f"Base URL: {self.base_url}, Team ID: {self.team_id}"
            )
        else:
            logger.warning(
                "SmartMemoryClient initialized WITHOUT authentication - "
                "most endpoints will fail. Call login() or provide api_key/token."
            )

    @property
    def is_authenticated(self) -> bool:
        """Check if client has valid authentication credentials."""
        return bool(self._token or self._api_key)

    @property
    def headers(self) -> Dict[str, str]:
        """Get headers with current auth token."""
        headers = self._base_headers.copy()
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # Legacy property for backwards compatibility
    @property
    def api_key(self) -> Optional[str]:
        """Get current auth credential (token or api_key)."""
        return self._token or self._api_key

    def refresh_token(
        self, refresh_token_value: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Refresh the JWT access token using the refresh token.

        Args:
            refresh_token_value: Refresh token to use. If not provided, uses internally stored token.

        Returns:
            Dict with new tokens

        Raises:
            SmartMemoryClientError: If refresh fails or no refresh token available
        """
        token_to_use = refresh_token_value or self._refresh_token
        if not token_to_use:
            raise SmartMemoryClientError(
                "No refresh token available. Call login() first or provide refresh_token."
            )

        body = {"refresh_token": token_to_use}
        result = self._request("POST", "/auth/refresh", json_body=body)

        if "access_token" in result:
            self._token = result["access_token"]
        if "refresh_token" in result:
            self._refresh_token = result["refresh_token"]

        logger.info("Token refreshed successfully")
        return result

    def logout(self) -> None:
        """
        Logout user and clear authentication tokens.

        Calls the server logout endpoint and clears local state.
        """
        try:
            self._request("POST", "/auth/logout")
        except Exception:
            pass  # Ignore errors on logout - still clear local state

        self._token = None
        self._refresh_token = None
        self._api_key = None
        logger.info("Logged out - credentials cleared")

    def close(self) -> None:
        """Close the underlying HTTP connection pool.

        Safe to call multiple times. After close(), the client should not be
        reused. Prefer the context-manager form (`with SmartMemoryClient(...)`)
        which closes automatically.
        """
        client = getattr(self, "_client", None)
        if client is not None:
            client.close()

    def __del__(self) -> None:
        # Best-effort pool cleanup if the caller never closed us. Interpreter
        # teardown can leave httpx partially collected, so swallow everything.
        try:
            self.close()
        except Exception:
            pass

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health status of the SmartMemory service.

        Returns:
            Health status information

        Example:
            ```python
            status = client.health_check()
            print(status)  # {'status': 'healthy'}
            ```
        """
        try:
            response = self._client.get(
                f"{self.base_url}/health", headers=self.headers, timeout=self.timeout
            )
            response.raise_for_status()
            return {"status": "healthy"}
        except httpx.HTTPStatusError as e:
            raise SmartMemoryClientError(f"Health check failed: {e}")
        except Exception as e:
            raise SmartMemoryClientError(f"Health check failed: {str(e)}")

    def archive_put(
        self,
        conversation_id: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Store a durable conversation artifact.

        Returns the archive URI and content hash required by the shared
        conversation ingestion flow.
        """
        return self._request(
            "POST",
            "/memory/archive/store",
            json_body={
                "conversation_id": conversation_id,
                "payload": payload,
                "metadata": metadata or {},
            },
        )

    def archive_get(self, archive_uri: str) -> Dict[str, Any]:
        """Retrieve an archived artifact by its archive URI."""
        encoded_archive_uri = quote(archive_uri, safe="/")
        return self._request("GET", f"/memory/archive/{encoded_archive_uri}")

    def add(
        self,
        item: Union[str, MemoryItem, Dict[str, Any]],
        memory_type: str = "semantic",
        metadata: Optional[Dict[str, Any]] = None,
        use_pipeline: bool = True,
        profile_name: Optional[str] = None,
        conversation_context: Optional[
            Union[ConversationContextModel, Dict[str, Any]]
        ] = None,
    ) -> str:
        """
        Add a memory item to the system.

        Args:
            item: Memory content (string) or MemoryItem object
            memory_type: Type of memory (semantic, episodic, procedural, working)
            metadata: Additional metadata for the memory
            use_pipeline: Whether to run full extraction pipeline (default: True)
            profile_name: Optional pipeline profile name (e.g. "lite", "full")
                routed server-side; selects an alternate pipeline configuration.
            conversation_context: Optional conversation context for
                conversation-aware entity extraction.

        Note:
            Provenance like `retrieved_context_ids` travels in `metadata` — the
            storage layer flattens metadata onto the node and lifts known fields
            back on read, so a dedicated wire field is unnecessary (GRAPH-API-1i,
            added then removed 2026-08-02).

        Returns:
            Memory item ID

        Example:
            ```python
            # Simple add
            item_id = client.add("Remember this")

            # With pipeline disabled (faster)
            item_id = client.add("Quick note", use_pipeline=False)

            # With a specific pipeline profile
            item_id = client.add("Tell me later", profile_name="lite")

            # With metadata
            item_id = client.add(
                "Important fact",
                metadata={"source": "user", "priority": "high"},
                use_pipeline=True
            )
            ```
        """
        # Handle different input types
        if isinstance(item, str):
            content = item
        elif isinstance(item, MemoryItem) or isinstance(
            getattr(item, "content", None), str
        ):
            # Duck-type MemoryItem-likes: callers (e.g. service_common record_turn)
            # pass smartmemory-core's MemoryItem, which is a different class from
            # the SDK's — a strict isinstance check silently stored str(item)
            # (the repr) as semantic content.
            content = item.content
            memory_type = getattr(item, "memory_type", None) or memory_type
            metadata = metadata or getattr(item, "metadata", None)
        elif isinstance(item, dict):
            content = item.get("content", str(item))
            memory_type = item.get("memory_type", memory_type)
            metadata = metadata or item.get("metadata")
        else:
            logger.warning(
                "add() received unrecognized item type %s; storing str(item) — content may "
                "be a repr, not real memory text",
                type(item).__name__,
            )
            content = str(item)

        body_dict = {
            "content": content,
            "memory_type": memory_type,
            "metadata": metadata or {},
            "use_pipeline": use_pipeline,
        }

        if profile_name is not None:
            body_dict["profile_name"] = profile_name

        if conversation_context:
            import dataclasses
            from datetime import date, datetime

            if hasattr(conversation_context, "to_dict"):
                # Core ConversationContext serializes its own datetimes (isoformat).
                body_dict["conversation_context"] = conversation_context.to_dict()
            elif dataclasses.is_dataclass(conversation_context) and not isinstance(
                conversation_context, type
            ):
                # dataclasses.asdict leaves datetime fields intact, which breaks
                # JSON encoding — normalize them here.
                body_dict["conversation_context"] = dataclasses.asdict(
                    conversation_context,
                    dict_factory=lambda pairs: {
                        k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
                        for k, v in pairs
                    },
                )
            else:
                body_dict["conversation_context"] = conversation_context

        try:
            result = self._request("POST", "/memory/add", json_body=body_dict)
        except SmartMemoryClientError as e:
            if "401" in str(e):
                logger.warning(
                    "Authentication required for add. Set SMARTMEMORY_API_KEY environment variable."
                )
            raise

        if not result:
            raise SmartMemoryClientError("Failed to add memory")

        if isinstance(result, dict):
            return result.get("id")
        elif hasattr(result, "id"):
            return result.id
        else:
            raise SmartMemoryClientError(f"Unexpected response format: {result}")

    def get(self, item_id: str) -> MemoryItem:
        """
        Retrieve a memory item by ID.

        Args:
            item_id: Memory item ID

        Returns:
            MemoryItem object.

        Raises:
            SmartMemoryNotFoundError: 404 — no item with that ID.
            SmartMemoryPermissionError: 401/403 — caller cannot read it.
            SmartMemoryServerError: 5xx — server failure.
            SmartMemoryClientError: any other transport or unexpected failure.

        Example:
            ```python
            try:
                memory = client.get("item_123")
                print(memory.content)
            except SmartMemoryNotFoundError:
                print("not found")
            ```
        """
        response = self._request("GET", f"/memory/{item_id}")
        if response is None:
            raise SmartMemoryNotFoundError(
                f"Request failed: empty 204 body for /memory/{item_id}",
                status_code=204,
            )
        return MemoryItem.from_dict(response)

    def search(
        self,
        query: str,
        top_k: int = 5,
        memory_type: Optional[str] = None,
        use_ssg: Optional[bool] = None,
        enable_hybrid: Optional[bool] = True,
        channel_weights: Optional[Dict[str, float]] = None,
        multi_hop: bool = False,
        max_hops: int = 3,
        budget_ms: int = 1500,
        expertise: bool = False,
        cite: bool = False,
        include_consolidated: bool = False,
        consolidation_first: bool = False,
        decompose: bool = False,
        semantic_hops: bool = False,
        include_reference: bool = False,
    ):
        """
        Search for memory items using semantic matching.

        Args:
            query: Search query
            top_k: Maximum number of results
            memory_type: Type of memory to search (optional)
            use_ssg: Use Similarity Graph Traversal for better multi-hop reasoning (optional)
                    If None, uses config default. If True, uses SSG. If False, uses basic vector search.
            enable_hybrid: Enable hybrid retrieval (vector + keyword search with RRF fusion).
                          Default: True. Set to False for vector-only search.
            channel_weights: Per-channel weight multipliers for RRF fusion (CORE-SEARCH-2a).
                           Keys: entity-graph, ssg-traversal, semantic, regex-text, contains, keyword-bm25.
                           Values: float multipliers (default varies by channel).
            expertise: When True (CORE-EXPERTISE-1 Phase 4a), returns a typed dict
                      keyed by expertise type instead of a flat list.
            include_consolidated: When True (CORE-CONSOLIDATE-1), include consolidated
                      source memories (normally hidden) in results.
            consolidation_first: When True (NEURO-1d), surface a consolidated summary above
                      the scattered source memories it consolidates — best for synthesis
                      queries ("what is known about X?"). Opt-in; implies include_consolidated.
            decompose: When True, the server decomposes a compound query into sub-queries
                      and fuses their results (SearchRequest.decompose).
            semantic_hops: When True with multi_hop, use LLM-driven hop planning
                      (CORE-MULTIHOP-2 / SearchRequest.semantic_hops).
            include_reference: When True, include reference data on returned items
                      (CORE-PROPS-1 Phase 6 / SearchRequest.include_reference).

        Returns:
            By default, ``List[MemoryItem]``.
            When ``expertise=True``, returns a ``Dict[str, List[MemoryItem]]`` keyed
            by expertise type (``decision``, ``constraint``, ``learned``, ``opinion``,
            ``reasoning``, ``observation``); each bucket holds up to ``top_k`` items.

        Example:
            ```python
            # Simple search (hybrid enabled by default)
            results = client.search("AI concepts", top_k=10)

            # Search with SSG for better multi-hop reasoning
            results = client.search("AI concepts", top_k=10, use_ssg=True)

            # Vector-only search (disable hybrid)
            results = client.search("AI concepts", enable_hybrid=False)

            # Search specific memory type
            results = client.search("conversation", memory_type="episodic")

            for item in results:
                print(f"{item.item_id}: {item.content}")
            ```

        Note:
            user_id is automatically determined from the JWT token.
            No need to pass it as a parameter.
        """
        # The FastAPI route expects a top-level SearchRequest body
        body_dict: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "enable_hybrid": enable_hybrid,
        }
        if memory_type is not None:
            body_dict["memory_type"] = memory_type
        if use_ssg is not None:
            body_dict["use_ssg"] = use_ssg
        if channel_weights is not None:
            body_dict["channel_weights"] = channel_weights
        if multi_hop:
            body_dict["multi_hop"] = True
            body_dict["max_hops"] = max_hops
            body_dict["budget_ms"] = budget_ms
        if expertise:
            body_dict["expertise"] = True
        if cite:
            body_dict["cite"] = True  # RECALL-CITATIONS-1
        if include_consolidated:
            body_dict["include_consolidated"] = True  # CORE-CONSOLIDATE-1
        if consolidation_first:
            body_dict["consolidation_first"] = True  # NEURO-1d
        if decompose:
            body_dict["decompose"] = True
        if semantic_hops:
            body_dict["semantic_hops"] = True  # CORE-MULTIHOP-2
        if include_reference:
            body_dict["include_reference"] = True  # CORE-PROPS-1 Phase 6

        # SELF-IMPROVE-6: use _request_raw to capture X-Search-Session-Id header
        url = f"{self.base_url}/memory/search"
        req_headers = {"X-Workspace-Id": self.team_id}
        if self.api_key:
            req_headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._client.request(
                "POST",
                url,
                json=body_dict,
                headers=req_headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            self._last_search_session_id = response.headers.get("X-Search-Session-Id")
            response_data = response.json()
        except httpx.HTTPStatusError as e:
            # Mirror _request: surface a typed subclass carrying status_code/detail
            # so callers can branch on SmartMemoryNotFoundError/PermissionError/etc.
            status = e.response.status_code if hasattr(e, "response") else 0
            error_detail = e.response.text if hasattr(e, "response") else str(e)
            exc_cls = _exception_for_status(status)
            raise exc_cls(
                f"Request failed: {e} - Detail: {error_detail}",
                status_code=status,
                detail=error_detail,
            ) from e
        except Exception as e:
            raise SmartMemoryClientError(f"Request failed: {str(e)}") from e

        # CORE-RECALL-LINEAGE-1 — `/memory/search` now always returns a
        # SearchResponse envelope: `{results, group_roots, citations?}`. Unwrap
        # the envelope ONCE to recover the bucket/list-shaped results, and stash
        # `group_roots` + `citations` on the client for `last_*` accessors.
        # RECALL-CITATIONS-1: cite=True attaches `citations` as a sibling key
        # (no longer double-wraps as it did pre-LINEAGE-1).
        self._last_citations: List[Dict[str, Any]] = []
        self._last_group_roots: Dict[str, Dict[str, Any]] = {}
        if isinstance(response_data, dict) and "results" in response_data:
            self._last_group_roots = dict(response_data.get("group_roots") or {})
            if cite:
                self._last_citations = list(response_data.get("citations") or [])
            response_data = response_data.get("results")

        if not response_data:
            return {} if expertise else []

        # CORE-EXPERTISE-1 Phase 4a: dict-of-lists shape when expertise=True.
        if expertise:
            # After envelope unwrap, response_data IS the bucket map directly.
            inner = response_data if isinstance(response_data, dict) else {}
            buckets: Dict[str, List[MemoryItem]] = {}
            for bucket_name, items in inner.items():
                buckets[bucket_name] = [
                    MemoryItem.from_dict(item)
                    for item in items
                    if isinstance(item, dict)
                ]
            return buckets

        # Convert response to MemoryItem objects
        results: List[MemoryItem] = []
        response_list = (
            response_data if isinstance(response_data, list) else [response_data]
        )

        for item_data in response_list:
            if hasattr(item_data, "to_dict"):
                item_dict = item_data.to_dict()
            elif isinstance(item_data, dict):
                item_dict = item_data
            else:
                continue

            # Use factory method for consistent parsing
            results.append(MemoryItem.from_dict(item_dict))

        return results

    @property
    def last_search_session_id(self) -> Optional[str]:
        """Return the search_session_id from the most recent search() call.

        Use this with submit_result_feedback() to report which results were used.
        """
        return getattr(self, "_last_search_session_id", None)

    @property
    def last_citations(self) -> List[Dict[str, Any]]:
        """Citations array from the most recent ``search(cite=True)`` call.

        Each entry has shape ``{n, item_id, item_type, preview, score, footnote_marker}``
        per the RECALL-CITATIONS-1 contract. Empty list when no citations were
        requested or no results were returned.
        """
        return list(getattr(self, "_last_citations", []) or [])

    @property
    def last_group_roots(self) -> Dict[str, Dict[str, Any]]:
        """CORE-RECALL-LINEAGE-1 — `group_roots` map from the most recent
        ``search()`` call.

        Keys are lineage root item_ids that appear in some result's
        ``lineage_roots`` but are not themselves in the result list. Each value
        is a ``GroupRootStub`` dict: ``{item_id, accessible, content_preview?,
        memory_type?, origin?}``. Empty dict when no out-of-result roots exist
        (the common case for queries that match canonicals directly).
        """
        return dict(getattr(self, "_last_group_roots", {}) or {})

    def get_working_context(
        self,
        session_id: str,
        query: str,
        k: int = 20,
        max_tokens: Optional[int] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Request a surfacing response from ``POST /memory/context``.

        Replacement for the legacy ``memory_recall`` surface (CORE-MEMORY-DYNAMICS-1 M1a).
        Response shape matches ``context-api-contract.json``.

        Args:
            session_id: Session scope for anchor resolution.
            query: Natural-language query for the surfacing turn.
            k: Item-count cap on returned items (1-100).
            max_tokens: Token budget cap; None disables.
            strategy: Override surfacing strategy; None lets the router decide.

        Returns:
            Dict with ``decision_id``, ``items``, ``drift_warnings``,
            ``strategy_used``, ``tokens_used``, ``tokens_budget``,
            ``deprecation`` keys (see contract).

        Raises:
            SmartMemoryClientError: Server returned 4xx/5xx (including
                ``budget_too_small``) or a transport error occurred.
        """
        body: Dict[str, Any] = {
            "session_id": session_id,
            "query": query,
            "k": k,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if strategy is not None:
            body["strategy"] = strategy
        return self._request("POST", "/memory/context", json_body=body)

    def search_advanced(
        self,
        query: str,
        algorithm: str = "query_traversal",
        max_results: int = 15,
        use_ssg: bool = True,
    ) -> List[MemoryItem]:
        """
        Advanced search using Similarity Graph Traversal (SSG) algorithms.

        SSG provides superior multi-hop reasoning and contextual retrieval compared to basic vector search.

        Args:
            query: Search query
            algorithm: SSG algorithm to use:
                      - "query_traversal": Best for general queries (100% test pass, 0.91 precision/recall)
                      - "triangulation_fulldim": Best for high precision (highest faithfulness)
            max_results: Maximum number of results to return
            use_ssg: Enable SSG traversal (vs basic vector search)

        Returns:
            List of MemoryItem objects

        Example:
            ```python
            # Best for general queries
            results = client.search_advanced("AI concepts", algorithm="query_traversal")

            # Best for high precision factual queries
            results = client.search_advanced("specific fact", algorithm="triangulation_fulldim")

            # Disable SSG (fallback to basic search)
            results = client.search_advanced("query", use_ssg=False)

            for item in results:
                print(f"{item.item_id}: {item.content}")
            ```

        Note:
            Based on research: github.com/glacier-creative-git/similarity-graph-traversal-semantic-rag-research
        """
        payload = {
            "query": query,
            "algorithm": algorithm,
            "max_results": max_results,
            "use_ssg": use_ssg,
        }

        data = self._request("POST", "/memory/search/advanced", json_body=payload)

        # Parse response using factory method
        results = []
        for item_dict in data.get("results", []):
            results.append(MemoryItem.from_dict(item_dict))

        return results

    def code_search(
        self,
        query: str,
        entity_type: Optional[str] = None,
        repo: Optional[str] = None,
        limit: int = 20,
        semantic: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search for code entities (classes, functions, routes, tests).

        Args:
            query: Search string (partial name match, or natural language when semantic=True)
            entity_type: Filter by type: module, class, function, route, test
            repo: Filter by repository name
            limit: Maximum results (default 20)
            semantic: Use vector similarity instead of name substring match

        Returns:
            List of code entity dicts with item_id, name, entity_type,
            file_path, line_number, docstring, repo, score (when semantic=True).

        Example:
            ```python
            # Name substring search (default)
            results = client.code_search("auth", entity_type="class")

            # Semantic search — natural language
            results = client.code_search("functions that handle payments", semantic=True)
            ```
        """
        params: Dict[str, Any] = {"query": query, "limit": limit, "semantic": semantic}
        if entity_type:
            params["entity_type"] = entity_type
        if repo:
            params["repo"] = repo
        return self._request("GET", "/memory/code/search", params=params)

    def code_index(
        self, path: str, repo: Optional[str] = None, commit: Optional[str] = None
    ) -> Dict[str, Any]:
        """Index code entities from a file or directory."""
        body: Dict[str, Any] = {"path": path}
        if repo:
            body["repo"] = repo
        if commit:
            body["commit"] = commit
        return self._request("POST", "/memory/code/index", json_body=body)

    def code_context(
        self, entity_name: str, repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get rich context for a code entity."""
        params: Dict[str, Any] = {"entity_name": entity_name}
        if repo:
            params["repo"] = repo
        return self._request("GET", "/memory/code/context", params=params)

    def code_dead_code(self, repo: str) -> Dict[str, Any]:
        """Find unreferenced code entities in a repository."""
        return self._request("GET", "/memory/code/dead-code", params={"repo": repo})

    def code_dependencies(
        self, entity_name: str, direction: str = "both", repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """Trace dependencies for a code entity."""
        params: Dict[str, Any] = {"entity_name": entity_name, "direction": direction}
        if repo:
            params["repo"] = repo
        return self._request("GET", "/memory/code/dependencies", params=params)

    def get_plan(self, plan_id: str) -> Dict[str, Any]:
        """Get a plan container with all its tasks."""
        return self._request("GET", f"/memory/plans/{plan_id}")

    def update_plan_task(
        self, plan_id: str, task_id: str, status: str
    ) -> Dict[str, Any]:
        """Update a task's status within a plan.

        Args:
            status: One of "pending", "in_progress", "complete", "blocked".
        """
        return self._request(
            "PATCH",
            f"/memory/plans/{plan_id}/task",
            json_body={"task_id": task_id, "status": status},
        )

    def complete_plan(self, plan_id: str, graduate: bool = False) -> Dict[str, Any]:
        """Mark a plan as completed. If graduate=True, also create a decision record."""
        return self._request(
            "POST",
            f"/memory/plans/{plan_id}/complete",
            json_body={"graduate": graduate},
        )

    def fail_plan(self, plan_id: str, reason: str) -> Dict[str, Any]:
        """Mark a plan as failed."""
        return self._request(
            "POST", f"/memory/plans/{plan_id}/fail", json_body={"reason": reason}
        )

    def update(
        self,
        item_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        properties: Optional[Dict[str, Any]] = None,
        write_mode: Optional[str] = None,
    ) -> None:
        """
        Update a memory item (CORE-CRUD-UPDATE-1 contract).

        Args:
            item_id: Memory item ID
            content: Convenience — folded into properties["content"]
            metadata: Convenience — deep-merged with existing metadata
            properties: Advanced — direct node-property dict. Takes precedence
                over content/metadata when provided.
            write_mode: "merge" (default) or "replace"

        Raises:
            SmartMemoryNotFoundError: 404 — no item with that ID.
            SmartMemoryPermissionError: 401/403 — caller cannot modify it.
            SmartMemoryValidationError: 400/422 — body rejected.
            SmartMemoryServerError: 5xx — server failure.
            SmartMemoryClientError: any other transport or unexpected failure.

        Examples:
            ```python
            client.update("item_123", content="Updated content")
            client.update("item_123", metadata={"updated": True})
            client.update("item_123",
                          properties={"importance_score": 0.9, "tags": ["v2"]})
            client.update("item_123",
                          properties={"content": "fresh"},
                          write_mode="replace")
            ```
        """
        body: Dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if metadata is not None:
            body["metadata"] = metadata
        if properties is not None:
            body["properties"] = properties
        if write_mode is not None:
            body["write_mode"] = write_mode

        self._request("PATCH", f"/memory/{item_id}", json_body=body)

    def supersede(
        self,
        item_id: str,
        *,
        content: str,
        memory_type: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append a replacement while retaining the prior item's history."""
        return self._request(
            "POST",
            f"/memory/{item_id}/supersede",
            json_body={
                "content": content,
                "memory_type": memory_type,
                "metadata": metadata or {},
                "reason": reason,
            },
        )

    def delete(self, item_id: str) -> None:
        """
        Delete a memory item.

        Args:
            item_id: Memory item ID

        Raises:
            SmartMemoryNotFoundError: 404 — no item with that ID.
            SmartMemoryPermissionError: 401/403 — caller cannot delete it.
            SmartMemoryServerError: 5xx — server failure.
            SmartMemoryClientError: any other transport or unexpected failure.

        Example:
            ```python
            client.delete("item_123")
            ```
        """
        self._request("DELETE", f"/memory/{item_id}")

    def ingest(
        self,
        content: str,
        extractor_name: str = "llm",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest content with full extraction and enrichment pipeline.

        Args:
            content: Content to ingest
            extractor_name: Name of the extractor to use (default: "llm")
            context: Additional context information

        Returns:
            Ingestion result with item_id, user_id, tenant_id, queued status

        Example:
            ```python
            # Ingest conversation
            result = client.ingest(
                content="User: Hello\nAssistant: Hi there!",
                extractor_name="llm",
                context={"conversation_id": "123", "timestamp": "2025-11-07"}
            )

            print(f"Ingested: {result['item_id']}")
            ```

        Note:
            user_id is automatically determined from the JWT token.
        """
        body_dict = {
            "content": content,
            "extractor_name": extractor_name,
            "context": context or {},
        }

        try:
            return self._request("POST", "/memory/ingest", json_body=body_dict)
        except Exception as e:
            raise SmartMemoryClientError(f"Failed to ingest content: {str(e)}")

    def ingest_conversation(
        self,
        turns: List[Dict[str, str]],
        session_boundaries: Optional[List[int]] = None,
        conversation_id: Optional[str] = None,
        session_dates: Optional[List[str]] = None,
        turns_per_chunk: int = 15,
        max_chunk_chars: int = 12000,
        max_concurrent: int = 4,
    ) -> Dict[str, Any]:
        """Ingest a conversation as session chunks through the full pipeline (RLM-1g).

        Args:
            turns: List of turn dicts with "role"/"speaker" and "content" keys.
            session_boundaries: Turn indices where sessions start (e.g. [0, 50, 120]).
            conversation_id: User-supplied ID (auto-generated if None).
            session_dates: ISO date per session for metadata.
            turns_per_chunk: Max turns per auto-chunk (default 15).
            max_chunk_chars: Safety split for oversized chunks (default 12000).
            max_concurrent: Semaphore limit for parallel chunk ingestion (default 4).

        Returns:
            Dict with conversation_id, conversation_node_id, chunks_ingested,
            chunks_failed, total_turns, total_chunks, chunk_results, total_duration_ms.
        """
        body_dict: Dict[str, Any] = {"turns": turns}
        if session_boundaries is not None:
            body_dict["session_boundaries"] = session_boundaries
        if conversation_id is not None:
            body_dict["conversation_id"] = conversation_id
        if session_dates is not None:
            body_dict["session_dates"] = session_dates
        if turns_per_chunk != 15:
            body_dict["turns_per_chunk"] = turns_per_chunk
        if max_chunk_chars != 12000:
            body_dict["max_chunk_chars"] = max_chunk_chars
        if max_concurrent != 4:
            body_dict["max_concurrent"] = max_concurrent

        try:
            return self._request(
                "POST", "/memory/ingest/conversation", json_body=body_dict
            )
        except Exception as e:
            raise SmartMemoryClientError(f"Failed to ingest conversation: {str(e)}")

    def link(self, source_id: str, target_id: str, link_type: str = "RELATED") -> bool:
        """
        Create a link between two memory items.

        Args:
            source_id: Source memory item ID
            target_id: Target memory item ID
            link_type: Type of link (RELATED, CAUSES, FOLLOWS, etc.)

        Returns:
            True if the link was created.

        Raises:
            SmartMemoryNotFoundError: 404 — source or target item does not exist.
            SmartMemoryPermissionError: 401/403 — caller cannot write the link.
            SmartMemoryValidationError: 400/409/422 — invalid link request.
            SmartMemoryServerError: 5xx — the link write failed server-side.
            SmartMemoryClientError: any other transport or unexpected failure.

        Example:
            ```python
            # Create relationship
            client.link("concept_1", "concept_2", link_type="RELATED")
            client.link("cause_id", "effect_id", link_type="CAUSES")
            ```
        """
        body_dict = {
            "source_id": source_id,
            "target_id": target_id,
            "link_type": link_type,
        }

        # Let _request's typed exceptions propagate (matching get/update/delete as of
        # 0.6.0). Previously every failure — 404, auth, 5xx, network — was collapsed
        # into a silent ``return False`` logged only at DEBUG, hiding real errors.
        self._request("POST", "/memory/link", json_body=body_dict)
        return True

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Add a direct edge between two nodes in the graph.

        This is a lower-level operation than link() - it creates a raw edge
        with custom properties. Use link() for standard memory linking.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            relation_type: Type of relation/edge
            properties: Optional edge properties

        Returns:
            Dict with edge creation result

        Example:
            ```python
            result = client.add_edge(
                source_id="node_1",
                target_id="node_2",
                relation_type="INFLUENCES",
                properties={"weight": 0.8, "confidence": 0.95}
            )
            ```
        """
        body = {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
            "properties": properties or {},
        }
        return self._request("POST", "/memory/edge", json_body=body)

    def get_neighbors(self, item_id: str) -> List[Dict[str, Any]]:
        """
        Get neighboring memory items (linked items).

        Args:
            item_id: Memory item ID

        Returns:
            List of neighbor information with item and link_type

        Example:
            ```python
            neighbors = client.get_neighbors("item_123")
            for neighbor in neighbors:
                print(f"{neighbor['item_id']}: {neighbor['link_type']}")
            ```
        """
        result = self._request("GET", f"/memory/{item_id}/neighbors")
        return result.get("neighbors", [])

    def get_edges_bulk(
        self, node_ids: List[str], include_properties: bool = False
    ) -> Dict[str, Any]:
        """Get all graph edges whose endpoints are in ``node_ids``.

        Args:
            node_ids: Node IDs to query (the service accepts up to 5,000).
            include_properties: Whether to include each edge's properties.

        Returns:
            Dict with ``edges`` and ``count``.
        """
        return self._request(
            "POST",
            "/memory/graph/edges",
            params={"include_properties": include_properties},
            json_body={"node_ids": node_ids},
        )

    def bulk_graph_upsert(
        self,
        nodes: Optional[List[Dict[str, Any]]] = None,
        edges: Optional[List[Dict[str, Any]]] = None,
        delete_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bulk upsert graph nodes and edges, optionally replacing a prefix.

        Args:
            nodes: Node dicts with ``item_id``, optional ``label``, and optional
                ``properties``.
            edges: Edge dicts with ``source_id``, ``target_id``, ``edge_type``,
                and optional ``properties``.
            delete_prefix: Delete scoped nodes with this ID prefix before writing.

        Returns:
            Dict with ``nodes_upserted``, ``edges_upserted``, and ``nodes_deleted``.
        """
        body: Dict[str, Any] = {"nodes": nodes or [], "edges": edges or []}
        if delete_prefix is not None:
            body["delete_prefix"] = delete_prefix
        return self._request("POST", "/memory/graph/bulk", json_body=body)

    def get_graph_path(
        self, start_id: str, end_id: str, max_hops: int = 5
    ) -> Dict[str, Any]:
        """Find the shortest graph path between two nodes.

        Args:
            start_id: Starting node ID.
            end_id: Destination node ID.
            max_hops: Maximum traversal depth (1-10).

        Returns:
            Dict with ``path_found``, ``hops``, and ``path``.
        """
        return self._request(
            "GET",
            "/memory/graph/path",
            params={"start_id": start_id, "end_id": end_id, "max_hops": max_hops},
        )

    def get_graph_full(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Get the workspace graph nodes and edges for visualization.

        Args:
            limit: Optional node limit; the service clamps it to its safety cap.

        Returns:
            Dict with ``nodes``, ``edges``, ``node_count``, and ``edge_count``.
        """
        params = {"limit": limit} if limit is not None else None
        return self._request("GET", "/memory/graph/full", params=params)

    def get_lineage(self, item_id: str) -> Dict[str, Any]:
        """Get the supersession lineage chain for a memory item."""
        return self._request("GET", f"/memory/{item_id}/lineage")

    def get_links(self, item_id: str) -> Dict[str, Any]:
        """Get all edges (links) for a memory item."""
        return self._request("GET", f"/memory/{item_id}/links")

    def search_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        memory_type: Optional[str] = None,
        limit: int = 25,
    ) -> Dict[str, Any]:
        """Search for a memory item by exact metadata key-value match."""
        params: Dict[str, Any] = {
            "metadata_key": metadata_key,
            "metadata_value": metadata_value,
            "limit": limit,
        }
        if memory_type:
            params["memory_type"] = memory_type
        return self._request("GET", "/memory/by-metadata", params=params)

    def get_recall_profile(self, agent_id: str) -> Dict[str, Any]:
        """Get an agent's recall profile for personality-aware retrieval."""
        return self._request("GET", f"/memory/agents/{agent_id}/recall-profile")

    def set_recall_profile(
        self, agent_id: str, recall_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Set an agent's recall profile. Send {} to clear."""
        return self._request(
            "PUT",
            f"/memory/agents/{agent_id}/recall-profile",
            json_body={"recall_profile": recall_profile},
        )

    def get_evaluation(
        self,
        agent_id: str,
        dimension: str,
        domain: str,
    ) -> Dict[str, Any]:
        """Get the current evaluation for an agent on a given (dimension, domain) slot.

        CORE-AGENT-2 S03-T10. Returns ``{evaluation: dict | null}``.
        ``null`` means no evaluation has been written yet (cold-start) — not an error.

        Args:
            agent_id: Agent identifier.
            dimension: Performance dimension (e.g. ``"decision_volume"``).
            domain: Domain string (e.g. ``"python"``).

        Returns:
            Response dict with ``evaluation`` key containing the current evaluation
            dict or ``None`` on cold-start.

        Raises:
            SmartMemoryNotFoundError: if ``agent_id`` is not found in the current tenant.
            SmartMemoryClientError: on any other HTTP error.
        """
        return self._request(
            "GET",
            f"/memory/agents/{agent_id}/evaluation",
            params={"dimension": dimension, "domain": domain},
        )

    def list_evaluation_history(
        self,
        agent_id: str,
        dimension: str,
        domain: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Get evaluation history for an agent on a given (dimension, domain) slot.

        CORE-AGENT-2 S03-T10. Returns ``{history: [dict, ...]}`` sorted most-recent-first.
        No ``include_history`` flag — use this method when history is needed.

        Args:
            agent_id: Agent identifier.
            dimension: Performance dimension.
            domain: Domain string.
            limit: Maximum records (default 20).

        Returns:
            Response dict with ``history`` key containing a list of evaluation dicts.

        Raises:
            SmartMemoryNotFoundError: if ``agent_id`` is not found in the current tenant.
            SmartMemoryClientError: on any other HTTP error.
        """
        return self._request(
            "GET",
            f"/memory/agents/{agent_id}/evaluation/history",
            params={"dimension": dimension, "domain": domain, "limit": limit},
        )

    def summary(self) -> Dict[str, Any]:
        """Get summary statistics about the memory system."""
        return self._request("GET", "/memory/summary")

    def enrich(
        self, item_id: str, routines: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Enrich a memory item with additional processing.

        Args:
            item_id: Memory item ID
            routines: List of enrichment routines to run

        Returns:
            Enrichment result

        Example:
            ```python
            result = client.enrich("item_123", routines=["sentiment", "keywords"])
            ```
        """
        body = {"item_id": item_id, "routines": routines or []}
        return self._request("POST", f"/memory/{item_id}/enrich", json_body=body)

    def personalize(
        self,
        traits: Optional[Dict[str, Any]] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Update personalization settings for the authenticated user.

        Args:
            traits: User traits
            preferences: User preferences

        Returns:
            Personalization result

        Example:
            ```python
            result = client.personalize(
                traits={"learning_style": "visual"},
                preferences={"language": "en", "complexity": "advanced"}
            )
            ```

        Note:
            user_id is automatically determined from the JWT token.
        """
        body = {"traits": traits or {}, "preferences": preferences or {}}
        return self._request("POST", "/memory/personalize", json_body=body)

    def cluster(
        self, distance_threshold: float = 0.1, dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Run entity clustering/deduplication for the workspace.

        Args:
            distance_threshold: Similarity threshold (0.0-1.0, default 0.1)
            dry_run: If true, preview clusters without merging

        Returns:
            Clustering results (merged_count, clusters_found, etc.)
        """
        params = {"distance_threshold": distance_threshold, "dry_run": dry_run}
        return self._request("POST", "/memory/clustering/run", params=params)

    def get_clustering_stats(self) -> Dict[str, Any]:
        """
        Get clustering statistics for the workspace.

        Returns:
            Clustering statistics
        """
        return self._request("GET", "/memory/clustering/stats")

    def resolve_aliases(
        self, dry_run: bool = False, disambiguate: bool = False
    ) -> Dict[str, Any]:
        """
        Merge fragmented single-token entity aliases into their canonical.

        Resolves unambiguous single-token entity surfaces (e.g. "Hudson") into
        their multi-token canonical (e.g. "Rock Hudson") over the caller's
        workspace graph, abstaining on collisions (>=2 candidates).

        Args:
            dry_run: If true, compute the resolve/abstain plan and report counts
                without mutating the graph.
            disambiguate: Opt-in (CORE-GRAPH-ALIAS-DISAMBIG-1, default False). Also
                recover colliding surfaces by structural typed-neighbor overlap —
                merge only on a confident, clear winner, else keep abstaining (never
                mis-merge). Extractor-dependent; helps LLM-extracted graphs.

        Returns:
            Resolve results (resolved, abstained, redirected_edges, ambiguous,
            disambiguated, dry_run, workspace_id, user_id).
        """
        params = {"dry_run": dry_run, "disambiguate": disambiguate}
        return self._request("POST", "/memory/graph/resolve-aliases", params=params)

    def dedup_entities(
        self, dry_run: bool = False, require_structural_confirmation: bool = True
    ) -> Dict[str, Any]:
        """
        Dedup cross-extractor fragmented entity nodes (CORE-GRAPH-CANONICAL-DEDUP-1).

        Collapses same-name entity-node fragments (the same entity split across >1
        node because two extractors disagreed on its type -> divergent canonical_key
        -> the write-time dedup missed them) into one node, precision-first, over the
        caller's workspace graph. Unblocks ensemble alias disambiguation. Opt-in,
        default-off. Recommended ensemble sequence: dedup_entities() then
        resolve_aliases(disambiguate=True).

        Args:
            dry_run: If true, compute the dedup plan and report counts without
                mutating the graph.
            require_structural_confirmation: If true (default), a same-name pair
                merges only on T0 (same Wikidata QID), T1 (same canonical_key), or
                T2 (>= tau_min shared typed entity-neighbors). If false, exact
                same-name clusters merge on name alone once T0/T1 fail (riskier
                disjoint-edge-tail recovery).

        Returns:
            Dedup results (merged_clusters, merged_nodes, redirected_edges,
            abstained_clusters, dry_run, workspace_id, user_id).
        """
        params = {
            "dry_run": dry_run,
            "require_structural_confirmation": require_structural_confirmation,
        }
        return self._request("POST", "/memory/graph/dedup-entities", params=params)

    def ground(
        self, item_id: str, source_url: str, validation: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ground a memory item to an external source for provenance.

        Args:
            item_id: Memory item ID
            source_url: URL of the source
            validation: Optional validation data

        Returns:
            Result message
        """
        body = {"item_id": item_id, "source_url": source_url, "validation": validation}
        return self._request("POST", f"/memory/{item_id}/ground", json_body=body)

    def get_summarize_prompt(self, item_id: str) -> Dict[str, Any]:
        """
        Generate a prompt template for summarizing a memory item.

        Args:
            item_id: Memory item ID

        Returns:
            Prompt template and metadata
        """
        return self._request("GET", f"/memory/{item_id}/prompt/summarize")

    def get_analyze_prompt(self, item_id: str) -> Dict[str, Any]:
        """
        Generate a prompt template for analyzing memory connections.

        Args:
            item_id: Memory item ID

        Returns:
            Prompt template and metadata
        """
        return self._request("GET", f"/memory/{item_id}/prompt/analyze")

    def ingest_full(
        self,
        content: str,
        extractor_name: str = "llm",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest content with full synchronous entity/relation extraction pipeline.

        Args:
            content: Content to ingest
            extractor_name: Name of the extractor to use (default: "llm")
            context: Additional context information

        Returns:
            Full ingestion result with entities and relations
        """
        body = {
            "content": content,
            "extractor_name": extractor_name,
            "context": context or {},
        }
        return self._request("POST", "/memory/ingest/full", json_body=body)

    # ============================================================================
    # Admin & Monitoring
    # ============================================================================

    def orphaned_notes(self) -> Dict[str, Any]:
        """Find orphaned notes (notes with no connections)."""
        return self._request("GET", "/memory/admin/orphaned-notes")

    def prune(
        self, strategy: str = "old", days: int = 365, dry_run: bool = True
    ) -> Dict[str, Any]:
        """Prune old or unused memories."""
        params = {"strategy": strategy, "days": days, "dry_run": dry_run}
        return self._request("POST", "/memory/admin/prune", params=params)

    def find_old_notes(self, days: int = 365) -> Dict[str, Any]:
        """Find notes older than N days."""
        return self._request("GET", "/memory/admin/old-notes", params={"days": days})

    def self_monitor(self) -> Dict[str, Any]:
        """Get self-monitoring metrics."""
        return self._request("GET", "/memory/admin/self-monitor")

    def get_system_stats(self) -> Dict[str, Any]:
        """Get comprehensive system statistics."""
        return self._request("GET", "/memory/admin/stats")

    def reflect(self, top_k: int = 5) -> Dict[str, Any]:
        """
        Reflect on memory patterns and insights.

        Analyzes memory content to identify patterns, themes,
        and potential connections.

        Args:
            top_k: Number of top items to reflect on

        Returns:
            Dict with reflection results including themes, patterns, suggestions

        Example:
            ```python
            reflection = client.reflect(top_k=10)
            print(reflection["reflection"]["themes"])
            ```
        """
        return self._request("GET", "/memory/admin/reflect", params={"top_k": top_k})

    def summarize(self, max_items: int = 10) -> Dict[str, Any]:
        """
        Generate a summary of memory contents.

        Creates a high-level overview of stored memories,
        including key topics, recent additions, and knowledge distribution.

        Args:
            max_items: Maximum items to include in summary

        Returns:
            Dict with summary including topic distribution, memory type breakdown

        Example:
            ```python
            summary = client.summarize(max_items=20)
            print(summary["summary"]["topic_distribution"])
            ```
        """
        return self._request(
            "GET", "/memory/admin/summarize", params={"max_items": max_items}
        )

    # ============================================================================
    # Agents
    # ============================================================================

    def create_agent(
        self,
        name: str,
        description: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new AI agent."""
        body = {
            "name": name,
            "description": description,
            "agent_config": agent_config or {},
            "roles": roles or ["user"],
        }
        return self._request("POST", "/memory/agents", json_body=body)

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all agents in the current tenant."""
        return self._request("GET", "/memory/agents")

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get details of a specific agent."""
        return self._request("GET", f"/memory/agents/{agent_id}")

    def delete_agent(self, agent_id: str) -> None:
        """Delete (deactivate) an agent."""
        self._request("DELETE", f"/memory/agents/{agent_id}")

    # ============================================================================
    # Analytics
    # ============================================================================

    def get_analytics_status(self) -> Dict[str, Any]:
        """Return analytics feature status."""
        return self._request("GET", "/memory/analytics/status")

    def detect_drift(self, time_window_days: int = 30) -> Dict[str, Any]:
        """Run concept drift detection."""
        return self._request(
            "GET",
            "/memory/analytics/drift",
            params={"time_window_days": time_window_days},
        )

    def detect_bias(
        self,
        protected_attributes: Optional[List[str]] = None,
        sentiment_analysis: Optional[bool] = None,
        topic_analysis: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Run bias detection."""
        body = {
            "protected_attributes": protected_attributes,
            "sentiment_analysis": sentiment_analysis,
            "topic_analysis": topic_analysis,
        }
        return self._request("POST", "/memory/analytics/bias", json_body=body)

    # ============================================================================
    # API Keys
    # ============================================================================

    def create_api_key(
        self,
        name: str,
        scopes: Optional[List[str]] = None,
        expires_in_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a new API key."""
        body = {
            "name": name,
            "scopes": scopes or ["read:memories"],
            "expires_in_days": expires_in_days,
        }
        return self._request("POST", "/memory/api-keys", json_body=body)

    def list_api_keys(self) -> List[Dict[str, Any]]:
        """List all API keys."""
        return self._request("GET", "/memory/api-keys")

    def revoke_api_key(self, key_id: str) -> None:
        """Revoke (delete) an API key."""
        self._request("DELETE", f"/memory/api-keys/{key_id}")

    # ============================================================================
    # Auth
    # ============================================================================

    def get_me(self) -> Dict[str, Any]:
        """Get current authenticated user info."""
        return self._request("GET", "/auth/me")

    def logout_all(self) -> None:
        """Logout from all devices."""
        self._request("POST", "/auth/logout-all")
        self._token = None
        self._refresh_token = None
        self._api_key = None

    def update_llm_keys(
        self,
        openai_key: Optional[str] = None,
        anthropic_key: Optional[str] = None,
        groq_key: Optional[str] = None,
        gemini_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update user's LLM provider API keys."""
        body = {
            "openai_key": openai_key,
            "anthropic_key": anthropic_key,
            "groq_key": groq_key,
            "gemini_key": gemini_key,
        }
        return self._request("PATCH", "/auth/llm-keys", json_body=body)

    def get_llm_keys(self) -> Dict[str, Any]:
        """Get user's LLM provider API keys (masked)."""
        return self._request("GET", "/auth/llm-keys")

    # ============================================================================
    # Evolve
    # ============================================================================

    def trigger_evolution(self) -> Dict[str, Any]:
        """Manually trigger memory evolution processes."""
        return self._request("POST", "/memory/evolution/trigger")

    def run_dream_phase(self) -> Dict[str, Any]:
        """Run a 'dream' phase: promote working memory to episodic/procedural."""
        return self._request("POST", "/memory/evolution/dream")

    def get_evolution_status(self) -> Dict[str, Any]:
        """Get status of memory evolution processes."""
        return self._request("GET", "/memory/evolution/status")

    # ============================================================================
    # Governance
    # ============================================================================

    def run_governance_analysis(
        self,
        query: str = "*",
        top_k: int = 100,
        memory_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run governance analysis."""
        body = {"query": query, "top_k": top_k, "memory_items": memory_items or []}
        return self._request("POST", "/memory/governance/run-analysis", json_body=body)

    def list_violations(
        self, severity: Optional[str] = None, auto_fixable_only: bool = False
    ) -> Dict[str, Any]:
        """List violations available for review."""
        params = {"severity": severity, "auto_fixable_only": auto_fixable_only}
        return self._request("GET", "/memory/governance/violations", params=params)

    def get_violation(self, violation_id: str) -> Dict[str, Any]:
        """Get a specific violation by ID."""
        return self._request("GET", f"/memory/governance/violations/{violation_id}")

    def apply_governance_decision(
        self,
        violation_id: str,
        action: str = "approve",
        rationale: str = "",
        decided_by: str = "human",
    ) -> Dict[str, Any]:
        """Apply a governance decision for a violation."""
        body = {
            "violation_id": violation_id,
            "action": action,
            "rationale": rationale,
            "decided_by": decided_by,
        }
        return self._request(
            "POST", "/memory/governance/apply-decision", json_body=body
        )

    def auto_fix_violations(self, confidence_threshold: float = 0.8) -> Dict[str, Any]:
        """Run auto-fix for high-confidence violations."""
        body = {"confidence_threshold": confidence_threshold}
        return self._request("POST", "/memory/governance/auto-fix", json_body=body)

    def get_governance_summary(self) -> Dict[str, Any]:
        """Get a summary of governance state."""
        return self._request("GET", "/memory/governance/summary")

    # ============================================================================
    # Ontology
    # ============================================================================

    def run_inference(
        self,
        raw_chunks: List[Dict[str, str]],
        registry_id: str = "default",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run ontology inference over provided raw text chunks."""
        body = {
            "registry_id": registry_id,
            "raw_chunks": raw_chunks,
            "params": params or {},
        }
        return self._request("POST", "/memory/ontology/inference/run", json_body=body)

    def list_registries(self) -> Dict[str, Any]:
        """List all ontology registries."""
        return self._request("GET", "/memory/ontology/registries")

    def create_registry(
        self, name: str, description: str = "", domain: str = "general"
    ) -> Dict[str, Any]:
        """Create a new ontology registry."""
        body = {"name": name, "description": description, "domain": domain}
        return self._request("POST", "/memory/ontology/registries", json_body=body)

    def get_registry_snapshot(
        self, registry_id: str, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get a snapshot of a registry (current or specific version)."""
        params = {"version": version} if version else None
        return self._request(
            "GET", f"/memory/ontology/registry/{registry_id}/snapshot", params=params
        )

    def apply_changeset(
        self,
        registry_id: str,
        changeset: Dict[str, Any],
        base_version: str = "",
        message: str = "",
    ) -> Dict[str, Any]:
        """Apply a changeset to create a new version of the registry."""
        body = {
            "base_version": base_version,
            "changeset": changeset,
            "message": message,
        }
        return self._request(
            "POST", f"/memory/ontology/registry/{registry_id}/apply", json_body=body
        )

    def list_registry_snapshots(
        self, registry_id: str, limit: int = 50
    ) -> Dict[str, Any]:
        """List snapshots for a registry."""
        return self._request(
            "GET",
            f"/memory/ontology/registry/{registry_id}/snapshots",
            params={"limit": limit},
        )

    def get_registry_changelog(
        self, registry_id: str, limit: int = 50
    ) -> Dict[str, Any]:
        """Get change history for a registry."""
        return self._request(
            "GET",
            f"/memory/ontology/registry/{registry_id}/changelog",
            params={"limit": limit},
        )

    def rollback_registry(
        self, registry_id: str, target_version: str = "", message: str = ""
    ) -> Dict[str, Any]:
        """Rollback registry to a previous version."""
        body = {"target_version": target_version, "message": message}
        return self._request(
            "POST", f"/memory/ontology/registry/{registry_id}/rollback", json_body=body
        )

    def list_ontology_hitl(
        self,
        status: str = "open",
        kind: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List ontology HITL queue items for the caller's workspace (ONTO-HITL-CONSUMER-1).

        Args:
            status: Filter by status (``open`` or ``resolved``).
            kind: Optional kind filter (``missing_in_graph`` / ``missing_in_registry``
                / ``name_conflict_unresolvable``).
            limit: Max rows (1-500).

        Returns:
            Dict with ``items``, ``count``, ``open_count``.
        """
        params: Dict[str, Any] = {"status": status, "limit": limit}
        if kind is not None:
            params["kind"] = kind
        return self._request("GET", "/memory/ontology/hitl", params=params)

    def resolve_ontology_hitl(
        self, item_id: str, action: str, note: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve one ontology HITL queue item (ONTO-HITL-CONSUMER-1).

        Args:
            item_id: The HITL item id.
            action: One of ``accepted`` / ``dismissed`` / ``deferred``.
            note: Optional free-text note.

        Returns:
            Dict with the updated ``item``.

        Raises:
            SmartMemoryNotFoundError: if the id is not in the caller's workspace (404).
            SmartMemoryValidationError: if ``action`` is invalid (422).
        """
        body: Dict[str, Any] = {"action": action, "note": note}
        return self._request(
            "POST", f"/memory/ontology/hitl/{item_id}/resolve", json_body=body
        )

    # --- ONTO-CRUD-1 read / audit / migration surface ---

    def list_ontology_types(
        self,
        tier: Optional[str] = None,
        layer: Optional[str] = None,
        pack_id: Optional[str] = None,
        has_iri: Optional[bool] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List ontology types, keyset-paginated (ONTO-CRUD-1).

        Args:
            tier: Filter by tier (``working``/``proposed``/``confirmed``/``retired``).
            layer: Filter by layer (``public``/``domain``/``private``).
            pack_id: Filter by originating pack id.
            has_iri: Only types with (or without) an IRI.
            limit: Page size (clamped to [1, 500]).
            cursor: Opaque keyset continuation token from a prior page.

        Returns:
            Dict with ``items`` and ``next_cursor``.

        Raises:
            SmartMemoryValidationError: if ``cursor`` is malformed (400).
        """
        params: Dict[str, Any] = {"limit": limit}
        if tier is not None:
            params["tier"] = tier
        if layer is not None:
            params["layer"] = layer
        if pack_id is not None:
            params["pack_id"] = pack_id
        if has_iri is not None:
            params["has_iri"] = has_iri
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", "/memory/ontology/types", params=params)

    def list_ontology_relations(
        self,
        tier: Optional[str] = None,
        layer: Optional[str] = None,
        pack_id: Optional[str] = None,
        has_iri: Optional[bool] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List ontology relation types, keyset-paginated (ONTO-CRUD-1). Mirror of ``list_ontology_types``.

        Args:
            tier: Filter by tier (``working``/``proposed``/``confirmed``/``retired``).
            layer: Filter by layer (``public``/``domain``/``private``).
            pack_id: Filter by originating pack id.
            has_iri: Only relations with (or without) an IRI.
            limit: Page size (clamped to [1, 500]).
            cursor: Opaque keyset continuation token from a prior page.

        Returns:
            Dict with ``items`` and ``next_cursor``.
        """
        params: Dict[str, Any] = {"limit": limit}
        if tier is not None:
            params["tier"] = tier
        if layer is not None:
            params["layer"] = layer
        if pack_id is not None:
            params["pack_id"] = pack_id
        if has_iri is not None:
            params["has_iri"] = has_iri
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", "/memory/ontology/relations", params=params)

    def get_ontology_type(self, type_id: str) -> Dict[str, Any]:
        """Resolve a single ontology type by iri/qid/name (ONTO-CRUD-1).

        Args:
            type_id: The type identifier (iri, qid, or name).

        Returns:
            Dict projection of the ontology type.

        Raises:
            SmartMemoryNotFoundError: if the type is not found (404).
        """
        return self._request("GET", f"/memory/ontology/types/{type_id}")

    def get_ontology_relation(self, relation_id: str) -> Dict[str, Any]:
        """Resolve a single ontology relation type by its identity (ONTO-CRUD-1).

        Args:
            relation_id: The relation identifier (iri, pid, or name).

        Returns:
            Dict projection of the ontology relation.

        Raises:
            SmartMemoryNotFoundError: if the relation is not found (404).
        """
        return self._request("GET", f"/memory/ontology/relations/{relation_id}")

    def list_ontology_audit(
        self,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Cross-entity, newest-first ontology audit feed (ONTO-CRUD-1).

        Args:
            actor: Filter by actor.
            action: Filter by action (e.g. ``migrate``, ``retire``).
            since: Full ISO-8601 lower bound (inclusive).
            until: Full ISO-8601 upper bound (inclusive).
            limit: Most-recent-N cap (clamped to [1, 1000]).

        Returns:
            Dict with ``items``.

        Raises:
            SmartMemoryValidationError: if ``since``/``until`` are malformed (400).
        """
        params: Dict[str, Any] = {"limit": limit}
        if actor is not None:
            params["actor"] = actor
        if action is not None:
            params["action"] = action
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        return self._request("GET", "/memory/ontology/audit", params=params)

    def get_ontology_type_audit(self, type_id: str) -> Dict[str, Any]:
        """Full append-only audit trail for one ontology type (oldest-first) (ONTO-CRUD-1).

        Args:
            type_id: The type identifier.

        Returns:
            Dict with ``items``.
        """
        return self._request("GET", f"/memory/ontology/types/{type_id}/audit")

    def get_ontology_relation_audit(self, relation_id: str) -> Dict[str, Any]:
        """Full append-only audit trail for one ontology relation (oldest-first) (ONTO-CRUD-1).

        Args:
            relation_id: The relation identifier.

        Returns:
            Dict with ``items``.
        """
        return self._request("GET", f"/memory/ontology/relations/{relation_id}/audit")

    def get_ontology_pack_audit(
        self, pack_id: str, pack_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Full append-only audit trail for a pack (oldest-first) (ONTO-CRUD-1).

        Args:
            pack_id: The pack identifier.
            pack_version: Scope to one installed version; omit for all.

        Returns:
            Dict with ``items``.
        """
        params: Dict[str, Any] = {}
        if pack_version is not None:
            params["pack_version"] = pack_version
        return self._request(
            "GET", f"/memory/ontology/packs/{pack_id}/audit", params=params
        )

    def migrate_ontology_type_instances(
        self, from_id: str, to_id: str, reason: str, batch_size: int = 500
    ) -> Dict[str, Any]:
        """Reclassify every instance of ``from_id`` onto ``to_id`` (ONTO-CRUD-1). Both types stay live.

        Args:
            from_id: The source type identifier.
            to_id: The destination type identifier.
            reason: Why the migration is being performed (audit evidence).
            batch_size: Instance edges rewritten per chunk (clamped to [1, 10000]).

        Returns:
            Dict with ``from_name``, ``into_name``, ``instances_migrated``, ``batches``, ``notes``.

        Raises:
            SmartMemoryValidationError: on a self-migration (``from_id == to_id``) (400).
            SmartMemoryNotFoundError: if either type is not found (404).
        """
        body: Dict[str, Any] = {"reason": reason, "batch_size": batch_size}
        return self._request(
            "POST",
            f"/memory/ontology/types/{from_id}/migrate-to/{to_id}",
            json_body=body,
        )

    def export_registry(
        self,
        registry_id: str,
        version: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export a registry snapshot."""
        params = {}
        if version:
            params["version"] = version
        if user_id:
            params["user_id"] = user_id
        return self._request(
            "GET", f"/memory/ontology/registry/{registry_id}/export", params=params
        )

    def import_registry(
        self, registry_id: str, data: Dict[str, Any], message: str = ""
    ) -> Dict[str, Any]:
        """Import data into a registry."""
        body = {"data": data, "message": message}
        return self._request(
            "POST", f"/memory/ontology/registry/{registry_id}/import", json_body=body
        )

    def list_enrichment_providers(self) -> Dict[str, Any]:
        """List available enrichment providers."""
        return self._request("GET", "/memory/ontology/enrichment/providers")

    def run_enrichment(
        self,
        entities: List[str],
        provider: str = "wikipedia",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run enrichment operation using specified provider."""
        body = {"provider": provider, "entities": entities, "user_id": user_id}
        return self._request("POST", "/memory/ontology/enrichment/run", json_body=body)

    def run_grounding_ontology(
        self,
        item_id: str,
        candidates: List[str],
        grounder: str = "wikipedia",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run grounding operation using specified grounder."""
        body = {
            "grounder": grounder,
            "item_id": item_id,
            "candidates": candidates,
            "user_id": user_id,
        }
        return self._request("POST", "/memory/ontology/grounding/run", json_body=body)

    # --- ONTO-HITL-CURATE-1 curation queue surface ---

    def list_ontology_review_queue(
        self,
        tier: Optional[str] = None,
        assignee: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List ontology review queue items, keyset-paginated (ONTO-HITL-CURATE-1).

        Args:
            tier: Filter by reviewable tier (``working``/``proposed``).
            assignee: Filter by review assignee.
            source: Filter by source string.
            limit: Page size (clamped to [1, 500]).
            cursor: Opaque keyset continuation token from a prior page.

        Returns:
            Dict with ``items`` and ``next_cursor``.

        Raises:
            SmartMemoryValidationError: if query parameters are invalid (400/422).
        """
        params: Dict[str, Any] = {"limit": limit}
        if tier is not None:
            params["tier"] = tier
        if assignee is not None:
            params["assignee"] = assignee
        if source is not None:
            params["source"] = source
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", "/memory/ontology/queue", params=params)

    def approve_ontology_type(
        self, type_id: str, expected_tier: Optional[str] = None
    ) -> Dict[str, Any]:
        """Approve one ontology review type.

        Args:
            type_id: Private-layer ontology type name.
            expected_tier: Optional optimistic tier precondition (``working``/``proposed``).

        Returns:
            Dict with ``ok``.

        Raises:
            SmartMemoryNotFoundError: if the type is not found or is cross-tenant (404).
            SmartMemoryValidationError: if ``expected_tier`` mismatches current state (409).
        """
        body: Dict[str, Any] = {}
        if expected_tier is not None:
            body["expected_tier"] = expected_tier
        encoded_type_id = quote(type_id, safe="")
        return self._request(
            "POST",
            f"/memory/ontology/queue/{encoded_type_id}/approve",
            json_body=body,
        )

    def reject_ontology_type(
        self, type_id: str, expected_tier: Optional[str] = None
    ) -> Dict[str, Any]:
        """Reject one ontology review type.

        Args:
            type_id: Private-layer ontology type name.
            expected_tier: Optional optimistic tier precondition (``working``/``proposed``).

        Returns:
            Dict with ``ok``.

        Raises:
            SmartMemoryNotFoundError: if the type is not found or is cross-tenant (404).
            SmartMemoryValidationError: if ``expected_tier`` mismatches current state (409).
        """
        body: Dict[str, Any] = {}
        if expected_tier is not None:
            body["expected_tier"] = expected_tier
        encoded_type_id = quote(type_id, safe="")
        return self._request(
            "POST",
            f"/memory/ontology/queue/{encoded_type_id}/reject",
            json_body=body,
        )

    def merge_ontology_review_type(
        self, type_id: str, into_id: str, expected_tier: Optional[str] = None
    ) -> Dict[str, Any]:
        """Merge one ontology review type into another type.

        Args:
            type_id: Private-layer ontology type name being reviewed.
            into_id: Destination type identifier.
            expected_tier: Optional optimistic tier precondition (``working``/``proposed``).

        Returns:
            Dict with ``ok``.

        Raises:
            SmartMemoryValidationError: if this is a self-merge (400) or tier mismatch (409).
            SmartMemoryNotFoundError: if either type is not found or is cross-tenant (404).
        """
        body: Dict[str, Any] = {"into_id": into_id}
        if expected_tier is not None:
            body["expected_tier"] = expected_tier
        encoded_type_id = quote(type_id, safe="")
        return self._request(
            "POST",
            f"/memory/ontology/queue/{encoded_type_id}/merge",
            json_body=body,
        )

    def edit_promote_ontology_type(
        self, type_id: str, edits: Dict[str, Any], expected_tier: Optional[str] = None
    ) -> Dict[str, Any]:
        """Edit and promote one ontology review type.

        Args:
            type_id: Private-layer ontology type name being reviewed.
            edits: Edit payload accepted by the service.
            expected_tier: Optional optimistic tier precondition (``working``/``proposed``).

        Returns:
            Dict with ``ok``.

        Raises:
            SmartMemoryValidationError: if edits are invalid (400) or tier mismatches (409).
            SmartMemoryNotFoundError: if the type is not found or is cross-tenant (404).
        """
        body: Dict[str, Any] = {"edits": edits}
        if expected_tier is not None:
            body["expected_tier"] = expected_tier
        encoded_type_id = quote(type_id, safe="")
        return self._request(
            "POST",
            f"/memory/ontology/queue/{encoded_type_id}/edit-promote",
            json_body=body,
        )

    def assign_ontology_review(
        self, type_id: str, assignee: Optional[str]
    ) -> Dict[str, Any]:
        """Assign or clear the reviewer for one ontology review type.

        Args:
            type_id: Private-layer ontology type name being reviewed.
            assignee: Reviewer identifier, or ``None`` to clear assignment.

        Returns:
            Dict with ``ok``.

        Raises:
            SmartMemoryNotFoundError: if the type is not found or is cross-tenant (404).
        """
        encoded_type_id = quote(type_id, safe="")
        return self._request(
            "POST",
            f"/memory/ontology/queue/{encoded_type_id}/assign",
            json_body={"assignee": assignee},
        )

    def bulk_ontology_review_action(
        self,
        action: str,
        ids: List[str],
        params: Optional[Dict[str, Any]] = None,
        expected_tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply a curation action to many ontology review types.

        Args:
            action: Bulk action (``approve``/``reject``/``merge``/``edit_promote``/``assign``).
            ids: Private-layer ontology type names to process.
            params: Action-specific params (``into_id``, ``edits``, or ``assignee``).
            expected_tier: Optional optimistic tier precondition (``working``/``proposed``).

        Returns:
            Dict with per-item ``results`` entries containing ``id``, ``ok``, and optional ``error``.
        """
        body: Dict[str, Any] = {"action": action, "ids": ids, "params": params or {}}
        if expected_tier is not None:
            body["expected_tier"] = expected_tier
        return self._request("POST", "/memory/ontology/queue/bulk", json_body=body)

    # ============================================================================
    # Pipeline
    # ============================================================================

    def run_extraction_stage(
        self, content: str, extractor_name: str = "llm"
    ) -> Dict[str, Any]:
        """Run extraction pipeline stage."""
        body = {"content": content, "extractor_name": extractor_name}
        return self._request("POST", "/memory/pipeline/extraction", json_body=body)

    def run_storage_stage(
        self, extracted_data: Dict[str, Any], storage_strategy: str = "standard"
    ) -> Dict[str, Any]:
        """Run storage pipeline stage."""
        body = {"extracted_data": extracted_data, "storage_strategy": storage_strategy}
        return self._request("POST", "/memory/pipeline/storage", json_body=body)

    def run_linking_stage(
        self, stored_entities: List[Dict[str, Any]], linking_algorithm: str = "exact"
    ) -> Dict[str, Any]:
        """Run linking pipeline stage."""
        body = {
            "stored_entities": stored_entities,
            "linking_algorithm": linking_algorithm,
        }
        return self._request("POST", "/memory/pipeline/linking", json_body=body)

    def run_enrichment_stage(
        self,
        linked_entities: List[Dict[str, Any]],
        enrichment_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run enrichment pipeline stage."""
        body = {
            "linked_entities": linked_entities,
            "enrichment_types": enrichment_types or ["sentiment", "topics"],
        }
        return self._request("POST", "/memory/pipeline/enrichment", json_body=body)

    def run_grounding_stage(
        self,
        enriched_entities: List[Dict[str, Any]],
        grounding_sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run grounding pipeline stage."""
        body = {
            "enriched_entities": enriched_entities,
            "grounding_sources": grounding_sources or ["wikipedia"],
        }
        return self._request("POST", "/memory/pipeline/grounding", json_body=body)

    def get_pipeline_state(
        self, pipeline_id: str, run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get pipeline state for a specific pipeline and run."""
        params = {"run_id": run_id} if run_id else None
        return self._request(
            "GET", f"/memory/pipeline/{pipeline_id}/state", params=params
        )

    def reset_pipeline(self, pipeline_id: str) -> Dict[str, Any]:
        """Reset a pipeline, clearing its state."""
        return self._request("DELETE", f"/memory/pipeline/{pipeline_id}")

    def clear_run_state(self, pipeline_id: str, run_id: str) -> Dict[str, Any]:
        """Clear all stage states for a specific pipeline run."""
        return self._request("DELETE", f"/memory/pipeline/{pipeline_id}/run/{run_id}")

    # ============================================================================
    # Subscription
    # ============================================================================

    def create_checkout_session(
        self,
        tier: str,
        billing_period: str = "monthly",
        trial_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a Stripe Checkout session for subscription upgrade."""
        body = {
            "tier": tier,
            "billing_period": billing_period,
            "trial_days": trial_days,
        }
        return self._request("POST", "/subscription/checkout", json_body=body)

    def upgrade_subscription(
        self,
        tier: str,
        billing_period: str = "monthly",
        payment_method_id: Optional[str] = None,
        use_checkout: bool = False,
    ) -> Dict[str, Any]:
        """Upgrade subscription tier."""
        body = {
            "tier": tier,
            "billing_period": billing_period,
            "payment_method_id": payment_method_id,
            "use_checkout": use_checkout,
        }
        return self._request("POST", "/subscription/upgrade", json_body=body)

    def get_subscription(self) -> Dict[str, Any]:
        """Get current subscription details."""
        return self._request("GET", "/subscription/current")

    def cancel_subscription(self, immediately: bool = False) -> Dict[str, Any]:
        """Cancel subscription."""
        return self._request(
            "POST", "/subscription/cancel", params={"immediately": immediately}
        )

    # ============================================================================
    # Teams
    # ============================================================================

    def create_team(
        self,
        name: str,
        description: Optional[str] = None,
        data_classification: str = "internal",
        cost_center: Optional[str] = None,
        is_system: bool = False,
    ) -> Dict[str, Any]:
        """Create a new team."""
        body = {
            "name": name,
            "description": description,
            "data_classification": data_classification,
            "cost_center": cost_center,
        }
        if is_system:
            body["is_system"] = True
        return self._request("POST", "/memory/teams", json_body=body)

    def list_teams(self, include_system: bool = False) -> List[Dict[str, Any]]:
        """List all teams the user has access to."""
        if include_system:
            return self._request(
                "GET", "/memory/teams", params={"include_system": True}
            )
        return self._request("GET", "/memory/teams")

    def get_team(self, team_id: str) -> Dict[str, Any]:
        """Get details of a specific team."""
        return self._request("GET", f"/memory/teams/{team_id}")

    def update_team(
        self,
        team_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        data_classification: Optional[str] = None,
        cost_center: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update team details."""
        body = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        if data_classification:
            body["data_classification"] = data_classification
        if cost_center:
            body["cost_center"] = cost_center
        return self._request("PATCH", f"/memory/teams/{team_id}", json_body=body)

    def delete_team(self, team_id: str) -> Dict[str, Any]:
        """Delete a team."""
        return self._request("DELETE", f"/memory/teams/{team_id}")

    def list_team_members(self, team_id: str) -> Dict[str, Any]:
        """List all members of a team."""
        return self._request("GET", f"/memory/teams/{team_id}/members")

    def add_team_member(
        self, team_id: str, user_id: str, role: str = "member"
    ) -> Dict[str, Any]:
        """Add a user to a team."""
        body = {"user_id": user_id, "role": role}
        return self._request("POST", f"/memory/teams/{team_id}/members", json_body=body)

    def update_team_member(
        self, team_id: str, member_user_id: str, role: str
    ) -> Dict[str, Any]:
        """Update a team member's role."""
        body = {"role": role}
        return self._request(
            "PATCH", f"/memory/teams/{team_id}/members/{member_user_id}", json_body=body
        )

    def remove_team_member(self, team_id: str, member_user_id: str) -> Dict[str, Any]:
        """Remove a user from a team."""
        return self._request(
            "DELETE", f"/memory/teams/{team_id}/members/{member_user_id}"
        )

    def get_team_permissions(self, team_id: str) -> Dict[str, Any]:
        """Get available permissions for a team."""
        return self._request("GET", f"/memory/teams/{team_id}/permissions")

    # ============================================================================
    # Temporal
    # ============================================================================

    def get_history(
        self,
        item_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Get complete version history of a memory item."""
        params = {"limit": limit}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self._request(
            "GET", f"/memory/temporal/{item_id}/history", params=params
        )

    def time_travel(
        self, timestamp: str, query: Optional[str] = None, limit: int = 100
    ) -> Dict[str, Any]:
        """Time-travel query - get state at specific time."""
        params = {"limit": limit}
        if query:
            params["query"] = query
        return self._request("GET", f"/memory/temporal/at/{timestamp}", params=params)

    def get_item_at_time(self, item_id: str, timestamp: str) -> Dict[str, Any]:
        """Get specific item as it existed at timestamp."""
        return self._request("GET", f"/memory/temporal/{item_id}/at/{timestamp}")

    def get_changes(
        self,
        item_id: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        change_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all changes to an item in time range."""
        params = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if change_type:
            params["change_type"] = change_type
        return self._request(
            "GET", f"/memory/temporal/{item_id}/changes", params=params
        )

    def compare_versions(self, item_id: str, v1: int, v2: int) -> Dict[str, Any]:
        """Compare two versions of an item."""
        params = {"v1": v1, "v2": v2}
        return self._request(
            "POST", f"/memory/temporal/{item_id}/compare", params=params
        )

    def rollback(
        self,
        item_id: str,
        to_version: Optional[int] = None,
        to_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rollback item to previous version."""
        params = {}
        if to_version:
            params["to_version"] = to_version
        if to_time:
            params["to_time"] = to_time
        return self._request(
            "POST", f"/memory/temporal/{item_id}/rollback", params=params
        )

    def get_audit_trail(
        self,
        item_id: str,
        change_type: Optional[str] = None,
        user_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get complete audit trail for an item."""
        params = {}
        if change_type:
            params["change_type"] = change_type
        if user_id:
            params["user_id"] = user_id
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self._request("GET", f"/memory/temporal/{item_id}/audit", params=params)

    def search_during_range(
        self, query: str, start_time: str, end_time: str, limit: int = 100
    ) -> Dict[str, Any]:
        """Search memories that existed during time range."""
        params = {
            "query": query,
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit,
        }
        return self._request("GET", "/memory/temporal/search/during", params=params)

    def generate_compliance_report(
        self,
        start_date: str,
        end_date: str,
        report_type: str = "HIPAA",
        item_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate compliance report (HIPAA, GDPR, SOC2)."""
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "report_type": report_type,
        }
        if item_ids:
            params["item_ids"] = item_ids
        return self._request("GET", "/memory/temporal/compliance/report", params=params)

    def get_relationship_history(self, rel_id: str) -> Dict[str, Any]:
        """Get history of a relationship."""
        return self._request("GET", f"/memory/temporal/relationships/{rel_id}/history")

    def get_relationships_at_time(
        self, timestamp: str, limit: int = 100
    ) -> Dict[str, Any]:
        """Get all relationships that existed at specific time."""
        params = {"limit": limit}
        return self._request(
            "GET", f"/memory/temporal/relationships/at/{timestamp}", params=params
        )

    def get_relationship_valid_periods(self, rel_id: str) -> Dict[str, Any]:
        """Get valid time periods for a relationship."""
        return self._request(
            "GET", f"/memory/temporal/relationships/{rel_id}/valid-periods"
        )

    # ============================================================================
    # Usage
    # ============================================================================

    def get_usage_dashboard(self) -> Dict[str, Any]:
        """Get usage dashboard with current quotas and limits."""
        return self._request("GET", "/usage/dashboard")

    def get_usage_limits(self) -> Dict[str, Any]:
        """Get quota limits for current subscription tier."""
        return self._request("GET", "/usage/limits")

    def get_current_usage(self) -> Dict[str, Any]:
        """Get current usage statistics."""
        return self._request("GET", "/usage/current")

    def get_available_tiers(self) -> Dict[str, Any]:
        """Get available subscription tiers."""
        return self._request("GET", "/usage/tiers")

    # ============================================================================
    # Token Usage (CFS-1)
    # ============================================================================

    def get_token_usage(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        group_by: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Get aggregated token usage history for the current workspace.

        Args:
            start_date: ISO date string (inclusive), e.g. "2026-02-01"
            end_date: ISO date string (inclusive), e.g. "2026-02-11"
            group_by: Group results by "stage", "profile", or "day"
            limit: Max records to return (1-1000, default 100)

        Returns:
            Dict with workspace_id, record_count, total_spent, total_avoided,
            savings_pct, records list, and optional grouping data.
        """
        params: Dict[str, Any] = {"limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if group_by:
            params["group_by"] = group_by
        return self._request("GET", "/memory/token-usage", params=params)

    def get_token_usage_current(self) -> Dict[str, Any]:
        """Get real-time token usage: cache stats + last 10 pipeline runs.

        Returns:
            Dict with workspace_id, cache_stats, and recent_runs list.
        """
        return self._request("GET", "/memory/token-usage/current")

    # ============================================================================
    # Procedure Matches (CFS-2)
    # ============================================================================

    def list_procedure_matches(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        procedure_id: Optional[str] = None,
        feedback: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List procedure match history for the current workspace.

        Args:
            start_date: ISO date string (inclusive), e.g. "2026-02-01"
            end_date: ISO date string (inclusive), e.g. "2026-02-12"
            procedure_id: Filter by matched procedure ID
            feedback: Filter by feedback value: "success", "failure", or "neutral"
            limit: Max records to return (1-1000, default 100)

        Returns:
            Dict with workspace_id, record_count, and records list.
        """
        params: Dict[str, Any] = {"limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if procedure_id:
            params["procedure_id"] = procedure_id
        if feedback:
            params["feedback"] = feedback
        return self._request("GET", "/memory/procedures/matches", params=params)

    def submit_procedure_match_feedback(
        self,
        match_id: str,
        feedback: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit feedback for a procedure match.

        Args:
            match_id: The match ID (uuid) from ingest response or match list.
            feedback: One of "success", "failure", "neutral".
            note: Optional explanation (max 500 chars).

        Returns:
            Dict with status, match_id, and feedback.
        """
        body: Dict[str, Any] = {"feedback": feedback}
        if note:
            body["note"] = note
        return self._request(
            "POST", f"/memory/procedures/matches/{match_id}/feedback", json_body=body
        )

    def submit_result_feedback(
        self,
        session_id: str,
        result_used: List[str],
    ) -> Dict[str, Any]:
        """Submit result-selection feedback for a completed search session (SELF-IMPROVE-6).

        Call this after using results from ``search()`` to tell SmartMemory which
        results were actually useful.  The ``session_id`` is available in the
        ``X-Search-Session-Id`` response header from ``POST /memory/search``.

        Args:
            session_id: Server-generated session ID from the search response
                (``X-Search-Session-Id`` header).
            result_used: Item IDs from the search results that you incorporated.
                Pass an empty list if none of the results were useful.

        Returns:
            Dict with ``status``, ``search_session_id``, ``result_used_count``,
            ``result_shown_count``.

        Raises:
            HTTPError 404: Session not found or expired (> 1 hour since search).
            HTTPError 400: result_used contains IDs not in the original result set.
            HTTPError 409: Feedback already submitted for this session.
        """
        return self._request(
            "POST",
            "/memory/result-feedback",
            json_body={"search_session_id": session_id, "result_used": result_used},
        )

    def get_procedure_match_stats(self) -> Dict[str, Any]:
        """Get aggregated procedure match statistics for the current workspace.

        Returns:
            Dict with total_matches, successful, failed, neutral, no_feedback,
            avg_confidence, and by_procedure breakdown.
        """
        return self._request("GET", "/memory/procedures/matches/stats")

    # ============================================================================
    # Procedure Catalog (CFS-3)
    # ============================================================================

    def list_procedures(
        self,
        limit: int = 50,
        offset: int = 0,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """List all procedural memories with aggregated match statistics.

        Args:
            limit: Max procedures to return (1-200, default 50)
            offset: Pagination offset (default 0)
            sort_by: Sort field - "match_count", "success_rate", "created_at", or "name"
            sort_order: Sort direction - "asc" or "desc" (default "desc")

        Returns:
            Dict with workspace_id, total_count, and procedures list.
            Each procedure has id, name, description, created_at, metadata, and match_stats.
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "sort_order": sort_order,
        }
        if sort_by:
            params["sort_by"] = sort_by
        return self._request("GET", "/memory/procedures", params=params)

    def get_procedure(
        self,
        procedure_id: str,
        include_matches: bool = True,
        match_limit: int = 20,
    ) -> Dict[str, Any]:
        """Get full procedure detail with recent match history.

        Args:
            procedure_id: The procedure ID to retrieve.
            include_matches: Whether to include recent match history (default True).
            match_limit: Max matches to include (1-100, default 20).

        Returns:
            Dict with id, name, description, content, created_at, updated_at,
            metadata, match_stats, and optionally recent_matches list.

        Raises:
            SmartMemoryClientError: If procedure not found (404).
        """
        params: Dict[str, Any] = {
            "include_matches": include_matches,
            "match_limit": match_limit,
        }
        return self._request("GET", f"/memory/procedures/{procedure_id}", params=params)

    # ============================================================================
    # Webhooks
    # ============================================================================

    def trigger_stripe_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> Dict[str, Any]:
        """Trigger a Stripe webhook event (mostly for testing)."""
        # Note: This sends raw body, but our _request helper assumes JSON or params.
        # For webhooks, we might need to send raw bytes if we were simulating real Stripe calls.
        # However, the client is typically used to INTERACT with the API, not send webhooks TO it.
        # But if we need to simulate it:
        headers = {"stripe-signature": signature}
        # We'll use json_body for convenience, but real Stripe sends raw bytes.
        # This method might be limited by _request implementation if strict raw body is needed.
        return self._request(
            "POST", "/webhooks/stripe", json_body=payload, headers=headers
        )

    # ============================================================================
    # Zettelkasten
    # ============================================================================

    def get_backlinks(self, note_id: str) -> Dict[str, Any]:
        """Get notes that link TO this note (backlinks)."""
        return self._request("GET", f"/memory/zettel/{note_id}/backlinks")

    def get_forward_links(self, note_id: str) -> Dict[str, Any]:
        """Get notes this note links TO (forward links)."""
        return self._request("GET", f"/memory/zettel/{note_id}/forward-links")

    def get_connections(self, note_id: str) -> Dict[str, Any]:
        """Get all connections (backlinks + forward links)."""
        return self._request("GET", f"/memory/zettel/{note_id}/connections")

    def get_clusters(
        self, min_size: int = 3, algorithm: str = "louvain"
    ) -> Dict[str, Any]:
        """Detect knowledge clusters in your Zettelkasten."""
        params = {"min_size": min_size, "algorithm": algorithm}
        return self._request("GET", "/memory/zettel/clusters", params=params)

    def get_hubs(self, min_connections: int = 5, limit: int = 20) -> Dict[str, Any]:
        """Find hub notes (highly connected notes)."""
        params = {"min_connections": min_connections, "limit": limit}
        return self._request("GET", "/memory/zettel/hubs", params=params)

    def get_bridges(self, limit: int = 20) -> Dict[str, Any]:
        """Find bridge notes (notes connecting different clusters)."""
        params = {"limit": limit}
        return self._request("GET", "/memory/zettel/bridges", params=params)

    def get_discoveries(
        self, note_id: str, max_distance: int = 3, min_surprise: float = 0.5
    ) -> Dict[str, Any]:
        """Find unexpected connections (serendipitous discovery)."""
        params = {"max_distance": max_distance, "min_surprise": min_surprise}
        return self._request(
            "GET", f"/memory/zettel/{note_id}/discoveries", params=params
        )

    def get_path(
        self, note_id: str, target_id: str, max_paths: int = 5
    ) -> Dict[str, Any]:
        """Find paths between two notes."""
        params = {"max_paths": max_paths}
        return self._request(
            "GET", f"/memory/zettel/{note_id}/path/{target_id}", params=params
        )

    def parse_wikilinks(self, content: str, auto_create: bool = True) -> Dict[str, Any]:
        """Parse [[wikilinks]] in content."""
        params = {"content": content, "auto_create": auto_create}
        return self._request("POST", "/memory/zettel/wikilink/parse", params=params)

    def resolve_wikilink(self, link: str) -> Dict[str, Any]:
        """Resolve a wikilink to a note."""
        params = {"link": link}
        return self._request("GET", "/memory/zettel/wikilink/resolve", params=params)

    def get_subgraph(
        self, note_id: str, depth: int = 2, include_metadata: bool = True
    ) -> Dict[str, Any]:
        """Get subgraph around a note (for visualization)."""
        params = {"depth": depth, "include_metadata": include_metadata}
        return self._request("GET", f"/memory/zettel/{note_id}/graph", params=params)

    def detect_concept_emergence(self, limit: int = 20) -> Dict[str, Any]:
        """Detect emerging concepts from connection patterns."""
        params = {"limit": limit}
        return self._request("GET", "/memory/zettel/concept-emergence", params=params)

    def suggest_related_notes(self, note_id: str, count: int = 5) -> Dict[str, Any]:
        """Suggest related notes for serendipitous discovery."""
        params = {"count": count}
        return self._request(
            "GET", f"/memory/zettel/{note_id}/suggestions", params=params
        )

    def random_walk_discovery(self, note_id: str, length: int = 5) -> Dict[str, Any]:
        """Perform random walk for serendipitous discovery."""
        params = {"length": length}
        return self._request(
            "GET", f"/memory/zettel/{note_id}/random-walk", params=params
        )

    def find_notes_by_tag(self, tag: str, limit: int = 100) -> Dict[str, Any]:
        """Find notes by tag."""
        params = {"limit": limit}
        return self._request("GET", f"/memory/zettel/by-tag/{tag}", params=params)

    def find_notes_by_property(
        self, key: str, value: str, limit: int = 100
    ) -> Dict[str, Any]:
        """Find notes by property."""
        params = {"key": key, "value": value, "limit": limit}
        return self._request("GET", "/memory/zettel/by-property", params=params)

    def find_notes_mentioning(self, entity_id: str, limit: int = 100) -> Dict[str, Any]:
        """Find notes mentioning an entity."""
        params = {"limit": limit}
        return self._request(
            "GET", f"/memory/zettel/mentioning/{entity_id}", params=params
        )

    def query_by_dynamic_relation(
        self, source_id: str, relation_type: str, limit: int = 100
    ) -> Dict[str, Any]:
        """Query notes by dynamic relation type."""
        params = {"limit": limit}
        return self._request(
            "GET",
            f"/memory/zettel/by-relation/{source_id}/{relation_type}",
            params=params,
        )

    # =========================================================================
    # Reasoning / Assertion Challenging
    # =========================================================================

    def challenge(
        self, assertion: str, memory_type: str = "semantic", use_llm: bool = True
    ) -> Dict[str, Any]:
        """
        Challenge an assertion against existing knowledge to detect contradictions.

        Uses a multi-method detection cascade:
        1. LLM-based (if enabled) - most accurate
        2. Graph-based - structural analysis
        3. Embedding-based - semantic similarity + polarity
        4. Heuristic - pattern matching fallback

        Args:
            assertion: The assertion to challenge
            memory_type: Type of memory to search (default: "semantic")
            use_llm: Use LLM for deep contradiction analysis

        Returns:
            Challenge result with conflicts, confidence, etc.

        Example:
            ```python
            result = client.challenge("Paris is the capital of Germany")
            if result["has_conflicts"]:
                for conflict in result["conflicts"]:
                    print(f"Contradicts: {conflict['existing_fact']}")
            ```
        """
        body = {"assertion": assertion, "memory_type": memory_type, "use_llm": use_llm}
        return self._request("POST", "/memory/reasoning/challenge", json_body=body)

    def resolve_conflict(
        self,
        existing_item_id: str,
        new_fact: str,
        auto_resolve: bool = True,
        strategy: Optional[str] = None,
        use_wikipedia: bool = True,
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """
        Resolve a conflict between assertions.

        Auto-resolution cascade (if enabled):
        1. Wikipedia lookup - verify against Wikipedia
        2. LLM reasoning - ask GPT to fact-check
        3. Grounding check - check existing provenance
        4. Recency heuristic - prefer recent info for temporal conflicts

        Args:
            existing_item_id: ID of the existing memory item in conflict
            new_fact: The new fact that conflicts
            auto_resolve: Attempt auto-resolution before manual strategy
            strategy: Manual resolution strategy if auto fails
                     ("keep_existing", "accept_new", "keep_both", "defer")
            use_wikipedia: Use Wikipedia for verification
            use_llm: Use LLM for reasoning

        Returns:
            Resolution result with method, evidence, confidence

        Example:
            ```python
            result = client.resolve_conflict(
                existing_item_id="item_123",
                new_fact="Paris is the capital of Germany",
                auto_resolve=True
            )
            if result["auto_resolved"]:
                print(f"Resolved via {result['method']}: {result['evidence']}")
            ```
        """
        body = {
            "existing_item_id": existing_item_id,
            "new_fact": new_fact,
            "auto_resolve": auto_resolve,
            "strategy": strategy,
            "use_wikipedia": use_wikipedia,
            "use_llm": use_llm,
        }
        return self._request("POST", "/memory/reasoning/resolve", json_body=body)

    def list_conflicts(
        self, needs_review: bool = True, limit: int = 50
    ) -> Dict[str, Any]:
        """
        List memory items that have unresolved conflicts.

        Args:
            needs_review: Filter to items needing review
            limit: Maximum number of items to return

        Returns:
            List of conflicting items with details

        Example:
            ```python
            conflicts = client.list_conflicts()
            for item in conflicts["conflicts"]:
                print(f"{item['item_id']}: {item['review_reason']}")
            ```
        """
        params = {"needs_review": needs_review, "limit": limit}
        return self._request("GET", "/memory/reasoning/conflicts", params=params)

    def get_low_confidence_items(
        self, threshold: float = 0.5, limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get items with confidence below threshold.

        Useful for finding facts that have been challenged multiple times
        and may need review or removal.

        Args:
            threshold: Confidence threshold (0.0-1.0)
            limit: Maximum items to return

        Returns:
            Items sorted by confidence (lowest first)

        Example:
            ```python
            low_conf = client.get_low_confidence_items(threshold=0.3)
            for item in low_conf["items"]:
                print(f"{item['item_id']}: {item['confidence']:.2f} ({item['challenge_count']} challenges)")
            ```
        """
        params = {"threshold": threshold, "limit": limit}
        return self._request("GET", "/memory/reasoning/low-confidence", params=params)

    def get_confidence_history(self, item_id: str) -> Dict[str, Any]:
        """
        Get the confidence decay history for a specific item.

        Args:
            item_id: Memory item ID

        Returns:
            Confidence history with timestamps, reasons, and conflicting facts

        Example:
            ```python
            history = client.get_confidence_history("item_123")
            print(f"Current confidence: {history['current_confidence']}")
            for event in history["history"]:
                print(f"  {event['timestamp']}: {event['old_confidence']:.2f} -> {event['new_confidence']:.2f}")
                print(f"    Reason: {event['reason']}")
            ```
        """
        return self._request("GET", f"/memory/reasoning/confidence-history/{item_id}")

    # =========================================================================
    # Reasoning Traces (System 2 Memory)
    # =========================================================================

    def extract_reasoning(
        self,
        content: str,
        min_steps: int = 2,
        min_quality_score: float = 0.4,
        use_llm_detection: bool = True,
    ) -> Dict[str, Any]:
        """
        Extract reasoning traces from content.

        Detects chain-of-thought reasoning patterns (Thought:/Action:/Observation:).

        Args:
            content: Content to extract reasoning from
            min_steps: Minimum steps required for a valid trace
            min_quality_score: Minimum quality score threshold
            use_llm_detection: Use LLM for implicit reasoning detection

        Returns:
            Extraction result with trace, has_reasoning, quality_score, step_count

        Example:
            ```python
            result = client.extract_reasoning('''
                Thought: I need to analyze this bug.
                Action: Let me search for the function.
                Observation: Found the issue in line 42.
                Conclusion: The fix is to add a null check.
            ''')
            if result['has_reasoning']:
                print(f"Found {result['step_count']} reasoning steps")
            ```
        """
        body = {
            "content": content,
            "min_steps": min_steps,
            "min_quality_score": min_quality_score,
            "use_llm_detection": use_llm_detection,
        }
        return self._request("POST", "/memory/reasoning/traces/extract", json_body=body)

    def store_reasoning_trace(
        self, trace: Dict[str, Any], artifact_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Store a reasoning trace as a memory item.

        Creates a 'reasoning' type memory with CAUSES relations to artifacts.

        Args:
            trace: Reasoning trace dict with trace_id, steps, task_context
            artifact_ids: IDs of artifacts this reasoning produced

        Returns:
            Storage result with trace_id, step_count, artifact_links

        Example:
            ```python
            result = client.store_reasoning_trace(
                trace={
                    "trace_id": "trace_123",
                    "steps": [
                        {"type": "thought", "content": "Analyzing the problem"},
                        {"type": "conclusion", "content": "Found the solution"},
                    ],
                    "task_context": {"goal": "Fix bug", "domain": "python"},
                },
                artifact_ids=["code_fix_456"]
            )
            ```
        """
        body = {
            "trace": trace,
            "artifact_ids": artifact_ids,
        }
        return self._request("POST", "/memory/reasoning/traces/store", json_body=body)

    def query_reasoning(
        self, query: str, artifact_id: Optional[str] = None, limit: int = 10
    ) -> Dict[str, Any]:
        """
        Query reasoning traces.

        Use cases:
        - "Why did I choose Python?" → finds reasoning traces about Python decisions
        - artifact_id → finds reasoning that led to this artifact

        Args:
            query: Query like "why did I choose X?"
            artifact_id: Find reasoning that led to this artifact
            limit: Maximum traces to return

        Returns:
            Query result with traces list and count

        Example:
            ```python
            # Find reasoning about a decision
            result = client.query_reasoning("why did I use async/await?")
            for trace in result['traces']:
                print(f"Trace {trace['trace_id']}: {trace['content'][:100]}...")

            # Find reasoning that led to an artifact
            result = client.query_reasoning("", artifact_id="code_123")
            ```
        """
        body = {
            "query": query,
            "artifact_id": artifact_id,
            "limit": limit,
        }
        return self._request("POST", "/memory/reasoning/traces/query", json_body=body)

    def get_reasoning_trace(self, trace_id: str) -> Dict[str, Any]:
        """
        Get a specific reasoning trace by ID.

        Args:
            trace_id: Reasoning trace ID

        Returns:
            Full reasoning trace with steps, task_context, artifact_ids
        """
        return self._request("GET", f"/memory/reasoning/traces/{trace_id}")

    # =========================================================================
    # Synthesis Evolution (Opinions & Observations)
    # =========================================================================

    def synthesize_opinions(self) -> Dict[str, Any]:
        """
        Run opinion synthesis: detect patterns in episodic memories and form opinions.

        Creates 'opinion' type memories with confidence scores based on recurring patterns.

        Returns:
            Synthesis result with status, message, timestamp

        Example:
            ```python
            result = client.synthesize_opinions()
            print(f"Status: {result['status']}")
            ```
        """
        return self._request("POST", "/memory/evolution/synthesize/opinions")

    def synthesize_observations(self) -> Dict[str, Any]:
        """
        Run observation synthesis: create entity summaries from scattered facts.

        Creates 'observation' type memories that summarize what we know about entities.

        Returns:
            Synthesis result with status, message, timestamp

        Example:
            ```python
            result = client.synthesize_observations()
            print(f"Status: {result['status']}")
            ```
        """
        return self._request("POST", "/memory/evolution/synthesize/observations")

    def reinforce_opinions(self) -> Dict[str, Any]:
        """
        Run opinion reinforcement: update confidence scores based on new evidence.

        Reinforces or contradicts existing opinions based on recent episodic memories.
        Archives opinions that fall below confidence threshold.

        Returns:
            Reinforcement result with status, message, timestamp

        Example:
            ```python
            result = client.reinforce_opinions()
            print(f"Status: {result['status']}")
            ```
        """
        return self._request("POST", "/memory/evolution/reinforce/opinions")

    # =========================================================================
    # Decision Memory
    # =========================================================================

    def create_decision(
        self,
        content: str,
        decision_type: str = "inference",
        confidence: float = 0.8,
        evidence_ids: Optional[List[str]] = None,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source_trace_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        rejected_alternatives: Optional[List[str]] = None,
        rationale: Optional[str] = None,
        constraints: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new decision with provenance tracking.

        Args:
            content: The decision statement.
            decision_type: One of inference, preference, classification, choice, belief, policy.
            confidence: Initial confidence score (0.0-1.0).
            evidence_ids: Memory IDs supporting this decision.
            domain: Domain tag for filtered retrieval.
            tags: Additional tags.
            source_trace_id: ReasoningTrace ID that produced this decision.
            source_session_id: Conversation session ID.
            rejected_alternatives: Alternatives considered and dropped (CORE-EXPERTISE-1).
            rationale: Why this decision over the alternatives (CORE-EXPERTISE-1).
            constraints: Decision-scoped hard limits (CORE-EXPERTISE-1).

        Returns:
            Created decision dict with decision_id, content, confidence, status.
        """
        body: Dict[str, Any] = {
            "content": content,
            "decision_type": decision_type,
            "confidence": confidence,
        }
        if evidence_ids:
            body["evidence_ids"] = evidence_ids
        if domain:
            body["domain"] = domain
        if tags:
            body["tags"] = tags
        if source_trace_id:
            body["source_trace_id"] = source_trace_id
        if source_session_id:
            body["source_session_id"] = source_session_id
        if rejected_alternatives:
            body["rejected_alternatives"] = rejected_alternatives
        if rationale is not None:
            body["rationale"] = rationale
        if constraints:
            body["constraints"] = constraints
        if agent_id is not None:
            body["agent_id"] = agent_id
        return self._request("POST", "/memory/decisions/create", json_body=body)

    def create_opinion(
        self,
        content: str,
        *,
        confidence: Optional[float] = None,
        subject: Optional[str] = None,
        subject_type: Optional[str] = None,
        disposition: Optional[Dict[str, Any]] = None,
        formed_from: Optional[List[str]] = None,
        domain: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new opinion with optional agent attribution.

        Mirrors POST /memory/opinions/create. ``agent_id`` is auto-populated
        server-side from the request scope when the caller is an agent-typed
        user (CORE-AGENT-ATTRIBUTION-1); supply it explicitly to override.

        Args:
            content: Opinion content (required).
            confidence: Initial confidence score (0.0-1.0).
            subject: Subject the opinion is about.
            subject_type: Type tag for the subject.
            disposition: Disposition payload (dict).
            formed_from: Source memory ids that contributed to the opinion.
            domain: Domain tag for filtered retrieval.
            agent_id: Producing agent id. If omitted and the caller's scope is
                agent-typed, the server fills this from ``resolve_agent_id()``.

        Returns:
            Created opinion dict with opinion_id, content, subject, confidence,
            agent_id, domain.
        """
        body: Dict[str, Any] = {"content": content}
        if confidence is not None:
            body["confidence"] = confidence
        if subject is not None:
            body["subject"] = subject
        if subject_type is not None:
            body["subject_type"] = subject_type
        if disposition is not None:
            body["disposition"] = disposition
        if formed_from is not None:
            body["formed_from"] = formed_from
        if domain is not None:
            body["domain"] = domain
        if agent_id is not None:
            body["agent_id"] = agent_id
        return self._request("POST", "/memory/opinions/create", json_body=body)

    def get_decision(self, decision_id: str) -> Dict[str, Any]:
        """Retrieve a decision by ID.

        Args:
            decision_id: The decision ID to retrieve.

        Returns:
            Decision dict with all fields.
        """
        return self._request("GET", f"/memory/decisions/{decision_id}")

    def list_decisions(
        self,
        domain: Optional[str] = None,
        decision_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        provenance_memory_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List active decisions with optional filters.

        Args:
            domain: Filter by domain.
            decision_type: Filter by type (inference, preference, etc.).
            min_confidence: Minimum confidence threshold.
            limit: Maximum results.
            provenance_memory_id: When set, returns only decisions whose provenance
                subgraph contains this memory id (CORE-DECISION-PROVENANCE-LOOKUP-1).
                Filters compose in-query so the response never silently truncates
                below ``limit`` when more matches exist. Unknown or out-of-scope
                memory ids return an empty list (never 404) to avoid existence leakage.

        Returns:
            List of decision dicts.
        """
        params: Dict[str, Any] = {"min_confidence": min_confidence, "limit": limit}
        if domain:
            params["domain"] = domain
        if decision_type:
            params["decision_type"] = decision_type
        if provenance_memory_id is not None:
            params["provenance_memory_id"] = provenance_memory_id
        if agent_id is not None:
            params["agent_id"] = agent_id
        result = self._request("GET", "/memory/decisions", params=params)
        return result.get("decisions", [])

    def supersede_decision(
        self,
        decision_id: str,
        new_content: str,
        reason: str,
        new_decision_type: str = "inference",
        new_confidence: float = 0.8,
    ) -> Dict[str, Any]:
        """Replace a decision with a new one.

        Args:
            decision_id: ID of the decision to supersede.
            new_content: Content of the replacement decision.
            reason: Why the old decision is being superseded.
            new_decision_type: Type of the new decision.
            new_confidence: Confidence of the new decision.

        Returns:
            Dict with old_decision_id, new_decision_id, status.
        """
        body = {
            "new_content": new_content,
            "reason": reason,
            "new_decision_type": new_decision_type,
            "new_confidence": new_confidence,
        }
        return self._request(
            "POST", f"/memory/decisions/{decision_id}/supersede", json_body=body
        )

    def retract_decision(self, decision_id: str, reason: str) -> Dict[str, Any]:
        """Retract a decision (mark as no longer valid).

        Args:
            decision_id: ID of the decision to retract.
            reason: Why the decision is being retracted.

        Returns:
            Dict with decision_id and status.
        """
        return self._request(
            "POST",
            f"/memory/decisions/{decision_id}/retract",
            json_body={"reason": reason},
        )

    def reinforce_decision(self, decision_id: str, evidence_id: str) -> Dict[str, Any]:
        """Record supporting evidence for a decision.

        Args:
            decision_id: ID of the decision to reinforce.
            evidence_id: Memory ID of the supporting evidence.

        Returns:
            Dict with decision_id, confidence, reinforcement_count.
        """
        return self._request(
            "POST",
            f"/memory/decisions/{decision_id}/reinforce",
            json_body={"evidence_id": evidence_id},
        )

    def contradict_decision(self, decision_id: str, evidence_id: str) -> Dict[str, Any]:
        """Record contradicting evidence against a decision.

        Args:
            decision_id: ID of the decision to contradict.
            evidence_id: Memory ID of the contradicting evidence.

        Returns:
            Dict with decision_id, confidence, and contradiction_count.
        """
        return self._request(
            "POST",
            f"/memory/decisions/{decision_id}/contradict",
            json_body={"evidence_id": evidence_id},
        )

    def get_decision_conflicts(
        self, decision_id: str, min_contest: float = 0.0
    ) -> Dict[str, Any]:
        """Find decisions that conflict with a decision.

        Args:
            decision_id: ID of the decision to inspect.
            min_contest: Minimum pairwise contest severity (0.0-1.0).

        Returns:
            Dict with decision_id, conflicts, and count.
        """
        return self._request(
            "POST",
            f"/memory/decisions/{decision_id}/conflicts",
            params={"min_contest": min_contest},
        )

    def search_decisions(self, topic: str, limit: int = 20) -> Dict[str, Any]:
        """Search active decisions related to a topic.

        Args:
            topic: Search topic.
            limit: Maximum matching decisions (1-100).

        Returns:
            Dict with decisions, count, and topic.
        """
        return self._request(
            "GET", "/memory/decisions/search", params={"topic": topic, "limit": limit}
        )

    def get_provenance_chain(self, decision_id: str) -> Dict[str, Any]:
        """Get full provenance chain for a decision.

        Args:
            decision_id: The decision ID.

        Returns:
            Dict with decision, reasoning_trace, evidence, superseded.
        """
        return self._request("GET", f"/memory/decisions/{decision_id}/provenance")

    def get_causal_chain(
        self,
        decision_id: str,
        direction: str = "both",
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """Trace causal chain from a decision.

        Args:
            decision_id: The decision ID.
            direction: 'causes', 'effects', or 'both'.
            max_depth: Maximum traversal depth (1-10).

        Returns:
            Dict with decision, causes, effects.
        """
        params = {"direction": direction, "max_depth": max_depth}
        return self._request(
            "GET", f"/memory/decisions/{decision_id}/causal-chain", params=params
        )

    def create_pending_decision(
        self,
        content: str,
        requirements: List[Dict[str, Any]],
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a pending decision (Acceptance Case) with unresolved requirements.

        Each requirement: {"description": str, "requirement_type": str, "query_hint": str|None}.
        Returns the decision incl. server-generated requirement_ids.
        """
        body: Dict[str, Any] = {"content": content, "requirements": requirements}
        if domain:
            body["domain"] = domain
        if tags:
            body["tags"] = tags
        if agent_id is not None:
            body["agent_id"] = agent_id
        return self._request("POST", "/memory/decisions/pending/create", json_body=body)

    def resolve_requirement(
        self, decision_id: str, requirement_id: str, memory_id: str
    ) -> Dict[str, Any]:
        """Mark one requirement on a pending decision resolved by a memory item."""
        return self._request(
            "POST",
            f"/memory/decisions/pending/{decision_id}/resolve",
            json_body={"requirement_id": requirement_id, "memory_id": memory_id},
        )

    def try_activate_decision(self, decision_id: str) -> Dict[str, Any]:
        """Try to activate a pending decision (no-op if requirements remain)."""
        return self._request(
            "POST", f"/memory/decisions/pending/{decision_id}/activate"
        )

    def list_pending_decisions(self, limit: int = 50) -> Dict[str, Any]:
        """List pending decisions awaiting more evidence."""
        return self._request(
            "GET", "/memory/decisions/pending", params={"limit": limit}
        )

    # =========================================================================
    # Procedure Evolution (CFS-3b)
    # =========================================================================

    def get_procedure_evolution(
        self,
        procedure_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get evolution history for a procedure.

        Returns a list of evolution events showing how the procedure was
        discovered and refined over time.

        Args:
            procedure_id: The procedure ID to get history for
            limit: Maximum number of events to return (default 20)
            offset: Number of events to skip (default 0)

        Returns:
            Dict with procedure_id, current_version, total_events, and events list

        Example:
            ```python
            history = client.get_procedure_evolution("proc_123")
            print(f"Current version: {history['current_version']}")
            for event in history['events']:
                print(f"  v{event['version']}: {event['event_type']} - {event['summary']}")
            ```
        """
        params = {"limit": limit, "offset": offset}
        return self._request(
            "GET", f"/memory/procedures/{procedure_id}/evolution", params=params
        )

    def get_procedure_evolution_event(
        self,
        procedure_id: str,
        event_id: str,
    ) -> Dict[str, Any]:
        """Get detailed information about a specific evolution event.

        Returns the full content snapshot and diff for a single evolution event.

        Args:
            procedure_id: The procedure ID
            event_id: The event ID to retrieve

        Returns:
            Full event detail including content_snapshot and changes_from_previous

        Example:
            ```python
            event = client.get_procedure_evolution_event("proc_123", "evt_456")
            print(f"Content at v{event['version']}:")
            print(event['content_snapshot']['content'])
            if event['changes_from_previous']['has_changes']:
                print(f"Changes: {event['changes_from_previous']['summary']}")
            ```
        """
        return self._request(
            "GET", f"/memory/procedures/{procedure_id}/evolution/{event_id}"
        )

    def get_procedure_confidence_trajectory(
        self,
        procedure_id: str,
    ) -> Dict[str, Any]:
        """Get confidence trajectory data for charting.

        Returns time-series data showing how confidence has changed over the
        procedure's lifecycle, suitable for rendering in a line chart.

        Args:
            procedure_id: The procedure ID

        Returns:
            Dict with procedure_id and data_points list containing timestamp,
            confidence, matches, and success_rate for each point

        Example:
            ```python
            trajectory = client.get_procedure_confidence_trajectory("proc_123")
            for point in trajectory['data_points']:
                print(f"{point['timestamp']}: confidence={point['confidence']:.2f}")
            ```
        """
        return self._request(
            "GET", f"/memory/procedures/{procedure_id}/confidence-trajectory"
        )

    # ============================================================================
    # Procedure Candidates (CFS-3b Recommendation Engine)
    # ============================================================================

    def list_procedure_candidates(
        self,
        min_score: float = 0.6,
        min_cluster_size: int = 3,
        days_back: int = 30,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        List procedure promotion candidates from working memory patterns.

        Analyzes working memory items to find repeated patterns that could be
        promoted to stored procedures for reuse.

        Args:
            min_score: Minimum recommendation score (0.0-1.0, default: 0.6)
            min_cluster_size: Minimum items in cluster (default: 3)
            days_back: Look back period in days (default: 30)
            limit: Maximum candidates to return (default: 20)

        Returns:
            Dict with workspace_id, candidate_count, total_working_items, and candidates list.
            Each candidate contains cluster_id, suggested_name, suggested_description,
            representative_content, item_count, scores, common_skills, common_tools,
            sample_item_ids, and date_range.

        Example:
            ```python
            result = client.list_procedure_candidates(min_score=0.7)
            for candidate in result['candidates']:
                print(f"{candidate['suggested_name']}: {candidate['scores']['recommendation_score']:.2f}")
            ```
        """
        params = {
            "min_score": min_score,
            "min_cluster_size": min_cluster_size,
            "days_back": days_back,
            "limit": limit,
        }
        return self._request("GET", "/memory/procedures/candidates", params=params)

    def promote_procedure_candidate(
        self,
        cluster_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        procedure_type: str = "extraction",
        preferred_profile: str = "quick_extract",
        remove_working_items: bool = False,
    ) -> Dict[str, Any]:
        """
        Promote a candidate cluster to a stored procedure.

        Creates a new procedural memory item from the candidate cluster's
        representative content and metadata.

        Args:
            cluster_id: The cluster ID from list_procedure_candidates
            name: Optional name for the procedure (uses suggested_name if omitted)
            description: Optional description for the procedure
            procedure_type: Type of procedure (default: "extraction")
            preferred_profile: Preferred pipeline profile (default: "quick_extract")
            remove_working_items: Remove working items after promotion (default: False)

        Returns:
            Dict with status, procedure_id, name, items_promoted, and items_removed

        Example:
            ```python
            result = client.promote_procedure_candidate(
                cluster_id="abc-123",
                name="API Error Handler",
                description="Handles 4xx errors from external APIs"
            )
            print(f"Created procedure: {result['procedure_id']}")
            ```
        """
        body = {
            "name": name,
            "description": description,
            "procedure_type": procedure_type,
            "preferred_profile": preferred_profile,
            "remove_working_items": remove_working_items,
        }
        return self._request(
            "POST",
            f"/memory/procedures/candidates/{cluster_id}/promote",
            json_body=body,
        )

    def dismiss_procedure_candidate(self, cluster_id: str) -> Dict[str, Any]:
        """
        Dismiss a candidate cluster from future recommendations.

        The candidate will be excluded from future recommendation lists
        for this workspace.

        Args:
            cluster_id: The cluster ID to dismiss

        Returns:
            Dict with status, cluster_id, and message

        Example:
            ```python
            result = client.dismiss_procedure_candidate("abc-123")
            print(result['message'])  # "Candidate dismissed from future recommendations"
            ```
        """
        return self._request(
            "DELETE", f"/memory/procedures/candidates/{cluster_id}/dismiss"
        )

    # ============================================================================
    # Procedure Schema Drift Detection (CFS-4)
    # ============================================================================

    def list_drift_events(
        self,
        procedure_id: Optional[str] = None,
        resolved: Optional[bool] = None,
        breaking_only: Optional[bool] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List schema drift events for the current workspace.

        Args:
            procedure_id: Filter by procedure ID.
            resolved: Filter by resolution status.
            breaking_only: If True, only return events with breaking changes.
            start_date: ISO 8601 date string for range start.
            end_date: ISO 8601 date string for range end.
            limit: Maximum number of events to return (1-1000, default 100).

        Returns:
            Dict with workspace_id, record_count, and records list of DriftEventSummary dicts.

        Example:
            ```python
            events = client.list_drift_events(resolved=False, breaking_only=True)
            for event in events["records"]:
                print(f"{event['procedure_id']}: {event['diff_summary']}")
            ```
        """
        params: Dict[str, Any] = {"limit": limit}
        if procedure_id is not None:
            params["procedure_id"] = procedure_id
        if resolved is not None:
            params["resolved"] = resolved
        if breaking_only is not None:
            params["breaking_only"] = breaking_only
        if start_date is not None:
            params["start_date"] = start_date
        if end_date is not None:
            params["end_date"] = end_date
        return self._request("GET", "/memory/procedures/drift", params=params)

    def get_drift_event(self, event_id: str) -> Dict[str, Any]:
        """
        Get a single drift event with full change details.

        Args:
            event_id: The drift event ID.

        Returns:
            DriftEventDetail dict with changes list, resolution info, and full metadata.

        Raises:
            SmartMemoryClientError: If event not found (404).

        Example:
            ```python
            event = client.get_drift_event("evt-abc-123")
            for change in event["changes"]:
                print(f"  {change['path']}: {change['change_type']} (breaking={change['breaking']})")
            ```
        """
        return self._request("GET", f"/memory/procedures/drift/{event_id}")

    def resolve_drift_event(
        self, event_id: str, note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mark a drift event as resolved.

        Args:
            event_id: The drift event ID to resolve.
            note: Optional resolution note (max 500 chars).

        Returns:
            Dict with status, event_id, and resolved=True.

        Raises:
            SmartMemoryClientError: If event not found (404).

        Example:
            ```python
            result = client.resolve_drift_event("evt-abc-123", note="Schema updated intentionally")
            ```
        """
        body: Dict[str, Any] = {}
        if note is not None:
            body["note"] = note
        return self._request(
            "POST", f"/memory/procedures/drift/{event_id}/resolve", json_body=body
        )

    def sweep_drift(self) -> Dict[str, Any]:
        """
        Trigger a drift sweep across all procedures in the workspace.

        Checks all procedures for schema drift against their stored snapshots.

        Returns:
            SweepResult dict with workspace_id, procedures_checked, drift_detected,
            and events_created counts.

        Example:
            ```python
            result = client.sweep_drift()
            print(f"Checked {result['procedures_checked']} procedures, "
                  f"found {result['drift_detected']} with drift")
            ```
        """
        return self._request("POST", "/memory/procedures/drift/sweep", json_body={})

    def list_schema_snapshots(self, procedure_id: str) -> Dict[str, Any]:
        """
        List schema snapshots for a procedure.

        Args:
            procedure_id: The procedure ID to get snapshots for.

        Returns:
            Dict with workspace_id, procedure_id, record_count, and snapshots list
            of SchemaSnapshotSummary dicts.

        Example:
            ```python
            result = client.list_schema_snapshots("proc-abc-123")
            for snap in result["snapshots"]:
                print(f"{snap['captured_at']}: {snap['tool_count']} tools, hash={snap['schema_hash']}")
            ```
        """
        return self._request("GET", f"/memory/procedures/schemas/{procedure_id}")

    # ------------------------------------------------------------------
    # Memory Snapshots (CORE-SUMMARY-1, E1)
    # ------------------------------------------------------------------

    def summary_generate(
        self,
        window_start: Optional[str] = None,
        include_markdown: bool = True,
    ) -> Dict[str, Any]:
        """Fire a manual snapshot for the current workspace.

        Returns the full snapshot payload. Raises ``SmartMemoryClientError``
        on conflict (HTTP 409 ``{reason: lock_held}``).
        """
        body: Dict[str, Any] = {"include_markdown": include_markdown}
        if window_start is not None:
            body["window_start"] = window_start
        return self._request("POST", "/memory/summary/generate", json_body=body)

    def summary_latest(self) -> Optional[Dict[str, Any]]:
        """Return the most recent snapshot for the current workspace, or
        ``None`` if none exists. Other errors (auth, 5xx) propagate."""
        try:
            return self._request("GET", "/memory/summary/latest")
        except SmartMemoryNotFoundError:
            return None

    def summary_get(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Return a specific snapshot by id, or ``None`` if not found.
        Other errors (auth, 5xx) propagate."""
        try:
            return self._request("GET", f"/memory/summary/{snapshot_id}")
        except SmartMemoryNotFoundError:
            return None

    def summary_list(
        self,
        is_heartbeat: Optional[bool] = None,
        limit: int = 20,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List snapshots for the current workspace, newest first."""
        params: Dict[str, Any] = {"limit": limit}
        if is_heartbeat is not None:
            params["is_heartbeat"] = str(is_heartbeat).lower()
        if before is not None:
            params["before"] = before
        return self._request("GET", "/memory/summary/list", params=params) or []

    def summary_delta(
        self,
        from_snapshot_id: str,
        to_snapshot_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the SnapshotDelta between two snapshots, or ``None`` if
        either snapshot is not found. Other errors (auth, 5xx) propagate."""
        try:
            return self._request(
                "GET",
                "/memory/summary/delta",
                params={"from": from_snapshot_id, "to": to_snapshot_id},
            )
        except SmartMemoryNotFoundError:
            return None

    def summary_delete(self, snapshot_id: str) -> None:
        """Admin-only. Delete a snapshot. Raises on 403/404/500."""
        self._request("DELETE", f"/memory/summary/{snapshot_id}")

    def export_okf(self) -> bytes:
        """Export this workspace as a gzipped OKF bundle."""
        response = self._request("GET", "/memory/okf/export", return_response=True)
        return response.content

    def import_okf(self, archive: bytes) -> dict:
        """Import a gzipped OKF bundle into this workspace."""
        return self._request(
            "POST",
            "/memory/okf/import",
            files={
                "file": (
                    "smartmemory-okf-import.tar.gz",
                    archive,
                    "application/gzip",
                )
            },
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        return_response: bool = False,
    ) -> Any:
        """Internal helper for making HTTP requests."""
        url = f"{self.base_url}{endpoint}"
        req_headers = {"X-Workspace-Id": self.team_id}
        if headers:
            req_headers.update(headers)

        if self.api_key:
            req_headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            request_kwargs: Dict[str, Any] = {
                "params": params,
                "json": json_body,
                "data": data,
                "headers": req_headers,
                "timeout": self.timeout,
            }
            if files is not None:
                request_kwargs["files"] = files
            response = self._client.request(
                method,
                url,
                **request_kwargs,
            )
            response.raise_for_status()
            if return_response:
                return response
            if response.status_code == 204:
                return None
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if hasattr(e, "response") else 0
            error_detail = e.response.text if hasattr(e, "response") else str(e)
            exc_cls = _exception_for_status(status)
            raise exc_cls(
                f"Request failed: {e} - Detail: {error_detail}",
                status_code=status,
                detail=error_detail,
            ) from e
        except Exception as e:
            raise SmartMemoryClientError(f"Request failed: {str(e)}") from e

    def feedback(
        self,
        item_ids: List[str],
        outcome: str,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit explicit feedback on recalled memory items.

        Adjusts ``retention_score`` immediately and, for ``helpful`` feedback with
        multiple items, strengthens ``CO_RETRIEVED`` edges between them — feeding
        directly into the Hebbian co-retrieval evolver.

        Args:
            item_ids: IDs of items returned by a prior ``search()`` call.
            outcome: ``"helpful"``, ``"misleading"``, or ``"neutral"``.
            query: Optional original search query (for context/logging).

        Returns:
            Dict with keys: ``updated`` (int), ``edges_strengthened`` (int), ``outcome`` (str).

        Example:
            ```python
            results = client.search("what did we decide about auth?")
            client.feedback([r.item_id for r in results], outcome="helpful")
            ```
        """
        body: Dict[str, Any] = {"item_ids": item_ids, "outcome": outcome}
        if query is not None:
            body["query"] = query
        return self._request("POST", "/memory/feedback", json_body=body)

    def __repr__(self) -> str:
        auth_status = "authenticated" if self.api_key else "unauthenticated"
        return f"SmartMemoryClient(base_url='{self.base_url}', {auth_status})"

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit — closes the persistent HTTP connection pool."""
        self.close()
