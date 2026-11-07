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

import json
import logging
import os
import re
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Sequence, Union
from urllib.parse import quote

import httpx

# Use local model instead of core dependency
from smartmemory_client.models.memory_item import MemoryItem
from smartmemory_client.models.conversation import ConversationContextModel
from smartmemory_client.models.routing import (
    RoutingEcho,
    RoutingExplain,
    RoutingPrefs,
    routing_echo,
)
from smartmemory_client.models.session import (
    SessionResponse,
    normalize_session_response,
)

from smartmemory_client import _save_transport as _transport
from smartmemory_client.receipt import Receipt, parse_receipt
from smartmemory_client.errors import (  # noqa: F401  (re-exported: the classes lived here before 2.0)
    STAGE_CHAIN_CODES,
    IdempotencyConflictError,
    ReceiptError,
    RetryKeyExpiredError,
    RevisionConflictError,
    SaveConflictError,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryRoutingConflictError,
    SmartMemoryServerError,
    SmartMemoryTransportError,
    SmartMemoryValidationError,
    StageChainError,
    SubmitScopeChangedError,
)

logger = logging.getLogger(__name__)


def _retry_after_s(response: Any) -> Optional[float]:
    """``Retry-After`` as seconds (delta-seconds or HTTP-date), or None when absent or unreadable."""
    value = (
        response.headers.get("Retry-After")
        if response is not None and hasattr(response, "headers")
        else None
    )
    if not value or not isinstance(value, (str, bytes, int, float)):
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        return max(
            0.0,
            (
                parsedate_to_datetime(str(value)) - datetime.now().astimezone()
            ).total_seconds(),
        )
    except (TypeError, ValueError):
        return None


class SmartMemoryUnsupportedError(SmartMemoryServerError):
    """Raised by the ``vector_*`` methods on HTTP 501: the active backend does not
    implement the capability (WEB-VECTOR-SEARCH-TAB-1). Never an empty result."""


class SmartMemorySubstrateError(SmartMemoryServerError):
    """Raised by the ``vector_*`` methods on HTTP 503: the vector backend reported a
    substrate error (``VectorSubstrateError``), surfaced instead of an empty page."""


def _body_error_code(detail: str) -> str | None:
    """Read the ``error`` code out of an error body: ``{"detail": {"error": code}}``,
    ``{"detail": "code"}`` or ``{"error": code}``. ``None`` when there is none (a 422
    list, plain text)."""
    try:
        body = json.loads(detail)
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    inner = body.get("detail", body)
    if isinstance(inner, dict):
        inner = inner.get("error")
    return inner if isinstance(inner, str) and inner else None


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


#: SVC-REQUEST-LATENCY-1 correlation/timing headers. The service echoes the
#: request id it accepted and reports its own time-to-response-start, so a caller
#: can split its wall time into "waiting on the service" and "network + our own
#: serialization" instead of guessing.
REQUEST_ID_HEADER = "X-Request-Id"
LATENCY_HEADER = "X-SM-Latency-Ms"

#: Same alphabet the service accepts. Validating here too means a bad id is
#: dropped at the source, where the caller can see the warning, rather than
#: silently ignored one process away.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

# CLIENT-CONN-REUSE-1: how long an idle pooled connection stays open. httpx's own
# default is 5 s, so a caller that pauses longer between calls (an agent loop
# waiting on a model) re-pays TCP + TLS (3 round trips, about 0.6 s at 260 ms RTT)
# on every call. Pool sizes below are httpx's defaults, restated because passing
# ``limits=`` replaces the whole object (``Limits()`` alone means "unlimited").
_KEEPALIVE_EXPIRY_S = 30.0
_POOL_LIMITS = dict(max_connections=100, max_keepalive_connections=20)


def _scoped_options(*, query: bool = False, **options: Any) -> Dict[str, Any]:
    """Copy supplied validity options, encoding dates in UTC and GET scope once.

    Validation belongs to the service so its status and details reach callers.
    None means omitted. Empty schedules remain supplied and are refused there.
    """

    def encode(value: Any) -> Any:
        if isinstance(value, datetime):
            aware = (
                value
                if value.tzinfo is not None
                else value.replace(tzinfo=timezone.utc)
            )
            return aware.astimezone(timezone.utc).isoformat()
        if isinstance(value, dict):
            return {key: encode(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [encode(child) for child in value]
        return value

    result = {key: encode(value) for key, value in options.items() if value is not None}
    if query and "business_scope" in result:
        result["business_scope"] = json.dumps(
            result["business_scope"], separators=(",", ":")
        )
    return result


def _as_of_params(as_of: Optional[str]) -> Dict[str, Any]:
    """``{"as_of": as_of}`` when set, else ``{}`` (SM-ASOF-DECISIONS-1).

    A call without ``as_of`` sends exactly the request it sent before. The value
    passes through unchanged: the server parses it and answers 400 ``invalid_as_of``
    when it is not an ISO 8601 instant.
    """
    return {} if as_of is None else {"as_of": as_of}


def _http2_available() -> bool:
    """True when the optional ``h2`` package is installed (``pip install smartmemory-client[http2]``).

    With HTTP/2, concurrent calls from threads share one connection instead of
    opening one each. The server negotiates it by ALPN and falls back to HTTP/1.1.
    """
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class RemoteCallTiming:
    """One observed HTTP call to the SmartMemory service.

    Attributes:
        method: HTTP method.
        path: URL path (no query string — ids in the path are kept, query values
            can carry user content).
        status_code: HTTP status returned.
        wall_ms: Time measured by this client, from request send to response
            **headers**. httpx fires its response hook before the body is read,
            which makes this the symmetric counterpart of the service's
            ``to_response_start_ms`` — neither number includes body transfer, so
            do not subtract one from the other expecting it to appear.
        server_ms: The service's own time-to-response-start from
            ``X-SM-Latency-Ms``, or ``None`` if the header was absent (an older
            service, or a response from a proxy that never reached it).
        request_id: The correlation id sent with the call, or ``""``.

    ``wall_ms - server_ms`` is network plus client-side overhead. That delta is
    the number worth watching: a small server_ms under a large wall_ms means the
    service is not the problem.
    """

    method: str
    path: str
    status_code: int
    wall_ms: float
    server_ms: Optional[float]
    request_id: str


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
        request_id_provider: Optional[Callable[[], Optional[str]]] = None,
        on_remote_call: Optional[Callable[["RemoteCallTiming"], None]] = None,
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
            request_id_provider: Called per request to supply a correlation id
                sent as ``X-Request-Id``. Return ``None`` to send none. Used by
                callers (Maya) that want their own log lines joinable with the
                service's. Ids must match ``[A-Za-z0-9._:-]{1,64}``.
            on_remote_call: Called after every response with a
                :class:`RemoteCallTiming`. Lets a caller attribute its own
                latency to remote service work. Never called for a request that
                failed before a response (connect/timeout errors) — those raise
                and are visible to the caller directly.

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
        #: Execution run ids of stage receipts returned by this client: never valid as a chain id (ST33).
        self._stage_receipt_runs: set = set()
        self.verify_ssl = verify_ssl

        # Persistent HTTP client for connection reuse (keep-alive pooling) across
        # the many per-method calls this SDK makes. Also the single place
        # verify_ssl is actually honored — the previous module-level httpx.request
        # / httpx.get calls never passed verify=, so verify_ssl was dead config.
        self._request_id_provider = request_id_provider
        self._on_remote_call = on_remote_call
        self._client = httpx.Client(
            verify=verify_ssl,
            timeout=timeout,
            limits=httpx.Limits(keepalive_expiry=_KEEPALIVE_EXPIRY_S, **_POOL_LIMITS),
            http2=_http2_available(),
            # Hooks rather than a wrapper around _request(): a few calls (health,
            # search-session) go through self._client directly, and a hook cannot
            # be bypassed by adding another one of those later.
            event_hooks={
                "request": [self._stamp_outgoing_request],
                "response": [self._observe_response],
            },
        )

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
        self.workspace_id = (
            workspace_id
            or team_id
            or os.getenv("SMARTMEMORY_WORKSPACE_ID")
            or os.getenv("SMARTMEMORY_TEAM_ID")
            or "team_default_demo"
        )
        if team_id is not None and not workspace_id:
            warnings.warn(
                "The 'team_id' parameter is deprecated and will be removed in v0.5.0. Use 'workspace_id' instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Build default headers (auth header added dynamically)
        self._base_headers = {
            "Content-Type": "application/json",
            "X-Workspace-Id": self.workspace_id,
        }

        if self.is_authenticated:
            logger.info(
                f"SmartMemoryClient initialized with authentication. Base URL: {self.base_url}, Workspace ID: {self.workspace_id}"
            )
        else:
            logger.warning(
                "SmartMemoryClient initialized WITHOUT authentication - "
                "most endpoints will fail. Call login() or provide api_key/token."
            )

    # ---- SVC-REQUEST-LATENCY-1: outgoing correlation + timing observation ----

    def _stamp_outgoing_request(self, request: httpx.Request) -> None:
        """Attach the caller's correlation id and start the clock.

        A provider that raises must not take the request down with it — telemetry
        is never worth a failed memory write — but it also must not vanish
        silently, so the loss is logged with what was lost.
        """
        request.extensions["sm_started"] = perf_counter()
        request.extensions["sm_request_id"] = ""
        if self._request_id_provider is None:
            return
        try:
            raw = self._request_id_provider()
        except Exception as error:
            logger.warning(
                "smartmemory_client: request_id_provider raised %s; "
                "sending request without a correlation id (lost=X-Request-Id)",
                type(error).__name__,
            )
            return
        request_id = (raw or "").strip()
        if not request_id:
            return
        if not _REQUEST_ID_RE.match(request_id):
            logger.warning(
                "smartmemory_client: request_id %r rejected (must match %s); "
                "sending request without a correlation id (lost=X-Request-Id)",
                request_id[:80],
                _REQUEST_ID_RE.pattern,
            )
            return
        request.headers[REQUEST_ID_HEADER] = request_id
        request.extensions["sm_request_id"] = request_id

    def _observe_response(self, response: httpx.Response) -> None:
        """Report one completed call to the caller's observer."""
        if self._on_remote_call is None:
            return
        started = response.request.extensions.get("sm_started")
        if started is None:
            return
        raw_server_ms = response.headers.get(LATENCY_HEADER)
        server_ms: Optional[float] = None
        if raw_server_ms is not None:
            try:
                server_ms = float(raw_server_ms)
            except ValueError:
                # A malformed header is a service bug, not a client one. Report
                # the call with server_ms=None rather than dropping the timing.
                logger.warning(
                    "smartmemory_client: unparseable %s header %r; "
                    "reporting call without server timing",
                    LATENCY_HEADER,
                    raw_server_ms[:40],
                )
        timing = RemoteCallTiming(
            method=response.request.method,
            path=response.request.url.path,
            status_code=response.status_code,
            wall_ms=(perf_counter() - started) * 1000.0,
            server_ms=server_ms,
            request_id=response.request.extensions.get("sm_request_id", ""),
        )
        try:
            self._on_remote_call(timing)
        except Exception as error:
            logger.warning(
                "smartmemory_client: on_remote_call raised %s; "
                "timing for %s %s discarded",
                type(error).__name__,
                timing.method,
                timing.path,
            )

    @property
    def is_authenticated(self) -> bool:
        """Check if client has valid authentication credentials."""
        return bool(self._token or self._api_key)

    @property
    def workspace_id(self) -> str:
        """Return the workspace used for ``X-Workspace-Id`` requests."""
        return self._workspace_id

    @workspace_id.setter
    def workspace_id(self, workspace_id: str) -> None:
        """Set the active workspace and keep the request header synchronized."""
        self._workspace_id = workspace_id
        if hasattr(self, "_base_headers"):
            self._base_headers["X-Workspace-Id"] = workspace_id

    @property
    def team_id(self) -> str:
        """Deprecated alias for :attr:`workspace_id`."""
        return self.workspace_id

    @team_id.setter
    def team_id(self, team_id: str) -> None:
        """Set :attr:`workspace_id` through the deprecated alias."""
        self.workspace_id = team_id

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
    ) -> SessionResponse:
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
        result = normalize_session_response(
            self._request("POST", "/auth/refresh", json_body=body)
        )

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
        embed: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> Receipt:
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
            embed: SVC-EMBED-CONTROL-1 embedding override. True forces an
                embedding, False suppresses one, None (default) leaves existing
                behaviour untouched. Only valid with ``use_pipeline=False`` —
                the service answers 400 for the combination rather than silently
                ignoring it, because the ingestion pipeline has no per-item
                override.
            idempotency_key: Request identity (``sm2_`` plus a UUID v4 when omitted).
                Automatic retries only follow 429 or proven connect-phase failures, up to four attempts.
                Hosted 2.0.0 does not replay request keys yet (SVC-2.0-SAVE-KEY-REPLAY-1).
                Check the write outcome before an explicit retry after a lost response, 408 or 5xx.

        Note:
            Provenance like `retrieved_context_ids` travels in `metadata` — the
            storage layer flattens metadata onto the node and lifts known fields
            back on read, so a dedicated wire field is unnecessary (GRAPH-API-1i,
            added then removed 2026-08-02).

        Returns:
            A :class:`Receipt` (2.0.0: this is no longer the bare item ID). ``receipt.item_id`` is the item
            handle; ``client.await_receipt(receipt)`` polls it to a stored, extracted or terminal state.

        Raises:
            RevisionConflictError, IdempotencyConflictError, RetryKeyExpiredError: HTTP 409 (all are
                ``SaveConflictError``); keep the draft, the SDK never mints a new key for you.
            ReceiptError: the server answered with a body that is not a readable 2.0 receipt.

        Example:
            ```python
            # Simple add
            item_id = client.add("Remember this").item_id

            # With pipeline disabled (faster)
            item_id = client.add("Quick note", use_pipeline=False).item_id

            # With a specific pipeline profile
            item_id = client.add("Tell me later", profile_name="lite").item_id

            # With metadata
            receipt = client.add(
                "Important fact",
                metadata={"source": "user", "priority": "high"},
                use_pipeline=True
            )
            ```
        """
        return self._add_response(
            item,
            memory_type,
            metadata,
            use_pipeline,
            profile_name,
            conversation_context,
            embed,
            idempotency_key=idempotency_key,
        )

    def add_detailed(
        self,
        item: Union[str, MemoryItem, Dict[str, Any]],
        memory_type: str = "semantic",
        metadata: Optional[Dict[str, Any]] = None,
        use_pipeline: bool = True,
        profile_name: Optional[str] = None,
        conversation_context: Optional[
            Union[ConversationContextModel, Dict[str, Any]]
        ] = None,
        embed: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> Receipt:
        """Same call and same :class:`Receipt` as ``add()`` (2.0.0: no longer the response dict).

        Kept so WS-ROUTING-2b callers keep working. The WS-ROUTING-2 write echo
        (``workspace_id``, ``workspace_name``, ``routed_by``, ``notices``) rides in
        ``receipt.raw``; ``routing_echo(receipt)`` reads it as typed fields (an older
        server omits them, which reads as ``None``). ``receipt.item_id`` is the item id.
        """
        return self._add_response(
            item,
            memory_type,
            metadata,
            use_pipeline,
            profile_name,
            conversation_context,
            embed,
            idempotency_key=idempotency_key,
        )

    def _add_response(
        self,
        item: Union[str, MemoryItem, Dict[str, Any]],
        memory_type: str = "semantic",
        metadata: Optional[Dict[str, Any]] = None,
        use_pipeline: bool = True,
        profile_name: Optional[str] = None,
        conversation_context: Optional[
            Union[ConversationContextModel, Dict[str, Any]]
        ] = None,
        embed: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> Receipt:
        """Shared ``POST /memory/add`` for ``add`` and ``add_detailed``: returns the save receipt."""
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

        # SVC-EMBED-CONTROL-1: send only when set, so an omitted argument is
        # byte-identical to the pre-feature request.
        if embed is not None:
            body_dict["embed"] = embed

        try:
            return self._save("/memory/add", body_dict, idempotency_key=idempotency_key)
        except SmartMemoryClientError as e:
            if "401" in str(e):
                logger.warning(
                    "Authentication required for add. Set SMARTMEMORY_API_KEY environment variable."
                )
            raise

    #: ST14/G173: a ``Retry-After`` that cannot fit in this many seconds ends the automatic retries.
    save_retry_deadline_s: float = _transport.AWAIT_TIMEOUT_S

    def _save(
        self,
        endpoint: str,
        body: Dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
        legacy_bridge: bool = True,
    ) -> Receipt:
        """POST one logical save under the ST14 retry policy and return its receipt.

        One key (the caller's, or a freshly minted ``sm2_`` UUID v4) rides in the body of every attempt, and the
        body is built once, so a retry is byte-identical. A 409 becomes the typed ``SaveConflictError``.
                before_retry=check_scope,
                retry_safe=endpoint != "/memory/add",
