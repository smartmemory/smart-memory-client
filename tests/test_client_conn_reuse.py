"""Connection reuse for every request path (CLIENT-CONN-REUSE-1).

A cold HTTPS request from far away costs 3 round trips (TCP, TLS, request). The SDK keeps
one pooled ``httpx.Client`` per ``SmartMemoryClient`` so calls after the first pay 1.
These tests fail when a request path builds its own client or connection, or when the
pool is configured so idle connections die quickly.

Real loopback server (HTTP/1.1 keep-alive) that counts accepted TCP connections. The port is
OS-assigned (port 0) and the server is shut down in the fixture teardown, pass or fail.
"""

import ast
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx
import pytest

import smartmemory_client.client as client_module
from smartmemory_client.client import SmartMemoryClient


class _CountingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.accepted = 0

    def get_request(self):
        conn = super().get_request()
        self.accepted += 1
        return conn


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive

    def _reply(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps({"status": "ok", "results": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = _reply

    def log_message(self, *args):  # silence
        pass


@pytest.fixture()
def server():
    srv = _CountingServer()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _client(srv):
    host, port = srv.server_address
    return SmartMemoryClient(
        base_url=f"http://{host}:{port}", api_key="sm_test_key", workspace_id="ws1"
    )


# One row per request-path class in client.py (grep table in
# units/CLIENT-CONN-REUSE-1/report.md): self._client.get (health), self._client.request
# in search() (reads a response header), and _request() with and without a body.
CALL_SITE_CLASSES = [
    ("health_check (self._client.get)", lambda c: c.health_check()),
    ("search (self._client.request, direct)", lambda c: c.search("q")),
    ("_request GET", lambda c: c._request("GET", "/memory/list")),
    (
        "_request POST json",
        lambda c: c._request("POST", "/memory/add", json_body={"a": 1}),
    ),
]


@pytest.mark.parametrize(
    "name,call", CALL_SITE_CLASSES, ids=[n for n, _ in CALL_SITE_CLASSES]
)
def test_each_request_path_reuses_one_connection(server, name, call):
    c = _client(server)
    try:
        for _ in range(4):
            call(c)
    finally:
        c.close()
    assert server.accepted == 1, (
        f"{name}: {server.accepted} TCP connections for 4 calls"
    )


def test_mixed_request_paths_share_one_connection(server):
    c = _client(server)
    try:
        for _, call in CALL_SITE_CLASSES * 2:
            call(c)
    finally:
        c.close()
    assert server.accepted == 1


def _pool_kwargs():
    with patch.object(client_module.httpx, "Client") as fake:
        c = SmartMemoryClient(base_url="http://x", api_key="sm_test_key")
        kwargs = dict(fake.call_args.kwargs)
        c.close()
    return kwargs


def test_idle_connections_outlive_httpx_default_expiry():
    limits = _pool_kwargs()["limits"]
    assert (
        limits.keepalive_expiry >= 30.0
    )  # httpx default 5.0 reconnects on every pause > 5 s
    assert limits.max_connections == 100
    assert limits.max_keepalive_connections == 20


# One row per branch of the optional-HTTP/2 switch.
@pytest.mark.parametrize("h2_installed", [True, False])
def test_http2_follows_the_optional_extra(h2_installed):
    with patch.object(client_module, "_http2_available", return_value=h2_installed):
        assert _pool_kwargs()["http2"] is h2_installed


def test_http2_probe_reflects_the_installed_package():
    try:
        import h2  # noqa: F401

        installed = True
    except ImportError:
        installed = False
    assert client_module._http2_available() is installed


def test_http2_client_builds_when_h2_is_installed():
    pytest.importorskip("h2")
    c = SmartMemoryClient(base_url="https://example.invalid", api_key="sm_test_key")
    try:
        assert c._client._transport._pool._http2 is True
    finally:
        c.close()


# ---- structural guard: no code path may build its own client ----

_SOURCE = pathlib.Path(client_module.__file__).read_text()
_TREE = ast.parse(_SOURCE)
_HTTPX_FACTORIES = {
    "Client",
    "AsyncClient",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "request",
    "stream",
}


def _httpx_calls():
    for node in ast.walk(_TREE):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
            and node.func.attr in _HTTPX_FACTORIES
        ):
            yield node.func.attr, node.lineno


def _enclosing_function(lineno):
    best = None
    for node in ast.walk(_TREE):
        if (
            isinstance(node, ast.FunctionDef)
            and node.lineno <= lineno <= node.end_lineno
        ):
            if best is None or node.lineno > best.lineno:
                best = node
    return best.name if best else None


def test_only_the_constructor_builds_an_httpx_client_and_nothing_makes_one_off_calls():
    calls = list(_httpx_calls())
    assert calls, "expected the pooled httpx.Client construction"
    for attr, lineno in calls:
        where = _enclosing_function(lineno)
        assert (attr, where) == ("Client", "__init__"), (
            f"client.py:{lineno} calls httpx.{attr} in {where}; use self._client so the pool is reused"
        )
    assert [a for a, _ in calls].count("Client") == 1


def test_no_other_module_in_the_package_opens_connections():
    pkg = pathlib.Path(client_module.__file__).parent
    offenders = []
    for path in pkg.rglob("*.py"):
        if path.name == "client.py":
            continue
        text = path.read_text()
        for needle in (
            "httpx.",
            "requests.",
            "urllib.request",
            "http.client",
            "aiohttp",
        ):
            if needle in text:
                offenders.append((path.name, needle))
    assert offenders == []


def test_close_releases_the_pool():
    c = SmartMemoryClient(base_url="http://x", api_key="sm_test_key")
    c.close()
    assert isinstance(c._client, httpx.Client) and c._client.is_closed
