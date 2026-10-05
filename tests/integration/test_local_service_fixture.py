"""SDK/direct-auth and the configured HTTP service use the same disposable stores."""
import httpx


def test_owned_local_service_roundtrip(service_url, test_user):
    from service_common.repositories.clients.mongodb import get_mongo_db
    from smartmemory_client import SmartMemoryClient
    db = get_mongo_db()
    try:
        assert db.name.startswith("sm_test_client_")
        assert db.users.find_one({"_id": test_user["user_id"]})
    finally:
        db.client.close()
    with SmartMemoryClient(base_url=service_url, token=test_user["access_token"],
                           team_id=test_user["workspace_id"]) as client:
        content = "Disposable local SDK fixture note"
        item_id = client.add(content, use_pipeline=False, embed=False)
        try:
            assert client.get(item_id).content == content
            from service_common.testing.auth import _retrieval_redis
            with _retrieval_redis() as retrieval:
                assert retrieval.sismember("smartmemory:active_workspaces", test_user["workspace_id"])
                assert retrieval.exists("smartmemory:retrievals:" + test_user["workspace_id"])
        finally:
            client.delete(item_id)
        headers = {"Authorization": "Bearer " + test_user["access_token"],
                   "X-Workspace-Id": test_user["workspace_id"]}
        assert httpx.get(service_url + "/memory/" + item_id, headers=headers).status_code == 404
