"""Run directly under neut.sh for pre-collection disposable-target launch."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

import pytest

pytestmark = pytest.mark.integration


def test_unrelated_run_survives_session_setup():
    if "H1_DISPOSABLE_DB" not in os.environ:
        launch()
        return
    from service_common.repositories.clients.mongodb import get_mongo_db

    db = get_mongo_db()
    try:
        assert db.name == os.environ["H1_DISPOSABLE_DB"]
        assert db.users.find_one({"_id": os.environ["H1_SENTINEL"]})
    finally:
        db.client.close()


def launch():
    from pymongo import MongoClient

    run = "test_h1_E2E_TEST_ISOLATION_1_" + uuid.uuid4().hex
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix=run) as scratch:
        config = Path(scratch) / "config.json"
        config.write_text(
            json.dumps(
                {
                    "mongodb": {"host": "localhost", "port": 9013, "database": run},
                    "graph_db": {
                        "host": "localhost",
                        "port": 9010,
                        "graph_name": run,
                        "main_graph_name": run,
                    },
                }
            )
        )
        env = {
            **os.environ,
            "SMARTMEMORY_CONFIG": str(config),
            "MONGODB_DB": run,
            "FALKORDB_HOST": "localhost",
            "FALKORDB_PORT": "9010",
            "REDIS_HOST": "localhost",
            "REDIS_PORT": "9012",
            "REDIS_DB": "14",
            "H1_DISPOSABLE_DB": run,
            "H1_SENTINEL": run + "_other",
            "SMARTMEMORY_TEST_GRAPH_NAME": run,
        }
        # Assert resolved targets BEFORE pytest imports conftest/autouse fixtures.
        preflight = "from service_common.repositories.clients.mongodb import get_mongo_db; import os; d=get_mongo_db(); assert d.name == os.environ['H1_DISPOSABLE_DB']; assert d.client.address == ('localhost',9013); d.client.close(); from service_common.services.tenant_purge import _get_falkordb,_get_redis; assert _get_falkordb().connection_pool.connection_kwargs['port']==9010; assert _get_redis().connection_pool.connection_kwargs['port']==9012"
        subprocess.run([sys.executable, "-c", preflight], env=env, check=True)
        db = MongoClient("mongodb://localhost:9013")[run]
        try:
            db.tenants.insert_one({"_id": run + "_other"})
            db.users.insert_one(
                {
                    "_id": run + "_other",
                    "tenant_id": run + "_other",
                    "email": run + "_other@example.test",
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(Path(__file__).resolve()),
                    "-q",
                    "-s",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=root,
                env=env,
                timeout=90,
            )
            assert result.returncode == 0, result.returncode
            assert db.users.find_one({"_id": run + "_other"}), (
                "unrelated B deleted at teardown"
            )
        finally:
            db.users.delete_one({"_id": run + "_other"})
            db.tenants.delete_one({"_id": run + "_other"})
            assert not db.users.count_documents({})
            db.client.drop_database(run)
            db.client.close()


if __name__ == "__main__":
    launch()


def test_fixture_finalizes_created_user_on_success_and_me_failure(
    tmp_path, monkeypatch, service_url
):
    """Real provisioning/cascade; only the HTTP response is fault-injected."""
    import importlib.util
    from types import SimpleNamespace
    from service_common.testing.auth import RunOwnership
    from service_common.repositories.clients.mongodb import get_mongo_db

    spec = importlib.util.spec_from_file_location(
        "client_fixture_under_test", Path(__file__).resolve().parents[1] / "conftest.py"
    )
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    db = get_mongo_db()
    owner = RunOwnership.create(tmp_path / "client-owner.json")
    sentinel = "test_h1_E2E_TEST_ISOLATION_1_" + uuid.uuid4().hex
    db.users.insert_one(
        {"_id": sentinel, "tenant_id": sentinel, "email": sentinel + "@example.test"}
    )
    try:
        for fail in (False, True):
            finalizers = []
            request = SimpleNamespace(addfinalizer=finalizers.append)

            def get(*args, fail=fail, **kwargs):
                user = db.users.find_one({"email": {"$in": owner.data["emails"]}})
                assert user
                return SimpleNamespace(
                    status_code=500 if fail else 200,
                    text="injected /auth/me result",
                    json=lambda: {
                        "tenant_id": user["tenant_id"],
                        "default_team_id": user["default_team_id"],
                    },
                )

            monkeypatch.setattr(fixture_module.httpx, "get", get)
            try:
                if fail:
                    with pytest.raises(pytest.fail.Exception):
                        fixture_module.test_user.__wrapped__(
                            "http://localhost:9001", True, owner, request
                        )
                else:
                    data = fixture_module.test_user.__wrapped__(
                        "http://localhost:9001", True, owner, request
                    )
                    assert db.users.find_one({"_id": data["user_id"]})
            finally:
                for finalizer in finalizers:
                    finalizer()
            assert not db.users.find_one({"email": {"$in": owner.data["emails"]}})
            assert db.users.find_one({"_id": sentinel})
            assert all(
                not any(counts.values()) for counts in owner.inventory().values()
            )
    finally:
        owner.finish()
        db.users.delete_one({"_id": sentinel})
        db.client.close()
