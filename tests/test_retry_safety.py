"""SDK-2.0-RETRY-SAFETY-1: real HTTP commit followed by a lost response."""

import json
import socket
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from smartmemory_client import SmartMemoryClient, SmartMemoryClientError


@pytest.mark.parametrize("failure", ["disconnect", 408, 429, 500, 502, 503, 504])
def test_add_does_not_duplicate_an_unconfirmed_commit(tmp_path, failure):
    db_path = tmp_path / "test_sdk_retry.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE items (body TEXT)")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            with sqlite3.connect(db_path) as db:
                db.execute("INSERT INTO items VALUES (?)", (body.decode(),))
            if failure == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            else:
                self.send_response(failure)
                self.end_headers()
                self.wfile.write(b"{}")

    server = HTTPServer(("127.0.0.1", 19086), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with SmartMemoryClient(
            base_url="http://127.0.0.1:19086",
            api_key="test_sdk_retry",
            team_id="test_sdk_retry",
        ) as client:
            with pytest.raises(SmartMemoryClientError) as caught:
                client.add(
                    "test_sdk_retry note",
                    use_pipeline=False,
                    embed=False,
                    idempotency_key="test_sdk_retry_key",
                )
        with sqlite3.connect(db_path) as db:
            rows = db.execute("SELECT body FROM items").fetchall()
        assert len(rows) == 1, "one logical add must commit at most once"
        error = caught.value
        assert type(error).__name__ == "WriteOutcomeUnknown"
        assert error.code == "write_outcome_unknown"
        assert error.attempts == 1
        assert error.idempotency_key == "test_sdk_retry_key"
        assert error.status_code == (None if failure == "disconnect" else failure)
        assert json.loads(rows[0][0])["embed"] is False
        assert "Check" in str(error)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        db_path.unlink()
