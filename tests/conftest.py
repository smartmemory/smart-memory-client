"""
Test configuration for smart-memory-client.

Provides fixtures for both unit tests and integration tests.
Integration tests require a running smart-memory-service.
"""

import os
import uuid

import pytest
import httpx


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (require running service)",
    )
    config.addinivalue_line(
        "markers", "golden: marks tests as golden flow tests (critical user journeys)"
    )
    config.addinivalue_line(
        "markers", "contract: marks tests as contract tests (API stability)"
    )
    config.addinivalue_line("markers", "harness: marks tests as error harness tests")
    config.addinivalue_line(
        "markers", "invariant: marks tests as invariant tests (logic kernels)"
    )
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (require external services)"
    )


# Default service URL for integration tests
SERVICE_URL = os.getenv("SMARTMEMORY_SERVICE_URL", "http://localhost:9001")


@pytest.fixture(scope="session")
def service_url():
    """Base URL for the SmartMemory service."""
    return SERVICE_URL


@pytest.fixture(scope="session")
def service_available(service_url):
    """Check if the service is available. Skip tests if not."""
    try:
        resp = httpx.get(f"{service_url}/health", timeout=5.0)
        if resp.status_code == 200:
            return True
    except Exception:
        pass
    pytest.skip(f"SmartMemory service not available at {service_url}")


@pytest.fixture(scope="session")
def owned_client_run():
    """Only integration provisioning needs the optional common dependency."""
    import tempfile
    from pathlib import Path
    from service_common.testing.auth import RunOwnership

    path = os.environ.get("SM_TEST_OWNERSHIP_MANIFEST") or str(
        Path(tempfile.mkdtemp(prefix="test_h1_E2E_TEST_ISOLATION_1_"))
        / "ownership.json"
    )
    owner = RunOwnership.create(path)
    try:
        yield owner
    finally:
        owner.finish()


@pytest.fixture(scope="class")
def test_user(service_url, service_available, owned_client_run, request):
    """Create a unique test user via direct DB provisioning.

    /auth/signup HTTP route no longer exists (removed in PLAT-SSO-IDP-1).
    Uses AuthService.signup() directly so no HTTP round-trip is needed for
    provisioning. Validates the provisioned session via /auth/me.

    Returns dict with:
        - email, password: credentials
        - access_token: JWT token for authentication
        - workspace_id, user_id, team_id: IDs
    """
    try:
        from service_common.services.auth_service import AuthService
        from service_common.repositories.factories import create_auth_repository
        from service_common.models.auth import SignupRequest
        from service_common.auth.jwt_singleton import get_jwt_manager
    except ImportError:
        pytest.skip(
            "service_common not available — integration tests require monorepo context"
        )

    unique_id = uuid.uuid4().hex[:8]
    email = f"{owned_client_run.data['prefix']}{unique_id}@example.com"
    owned_client_run.intend(email)
    # Register before creation, so signup or /auth/me failures still finalize.
    class_tenants = set()

    def finalize_user():
        from service_common.repositories.clients.mongodb import get_mongo_db

        owned_client_run.capture()
        db = get_mongo_db()
        try:
            class_tenants.update(
                user["tenant_id"]
                for user in db.users.find({"email": email}, {"tenant_id": 1})
            )
        finally:
            db.client.close()
        owned_client_run.cleanup(sorted(class_tenants))

    request.addfinalizer(finalize_user)
    password = "TestPassword123!"

    repo = create_auth_repository()
    # AuthService now requires a JWTManager (mirrors service.py:377). Use the
    # process singleton — same instance the running service signs tokens with,
    # so fixture-minted sessions validate against /auth/me.
    auth_service = AuthService(repo, get_jwt_manager())
    user_response, tokens = auth_service.signup(
        SignupRequest(
            email=email, password=password, full_name=f"Test User {unique_id}"
        )
    )

    owned_client_run.capture()
    class_tenants.add(user_response.tenant_id)

    # Validate the provisioned session via /auth/me (still present)
    resp = httpx.get(
        f"{service_url}/auth/me",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
        timeout=10.0,
    )
    if resp.status_code != 200:
        pytest.fail(f"/auth/me failed ({resp.status_code}): {resp.text}")

    me = resp.json()
    return {
        "email": email,
        "password": password,
        "access_token": tokens.access_token,
        "workspace_id": me.get("tenant_id"),
        "tenant_id": me["tenant_id"],
        "user_id": user_response.id,
        "team_id": me.get("default_team_id"),
    }


@pytest.fixture(scope="class")
def authenticated_client(service_url, test_user):
    """Create an authenticated SmartMemoryClient.

    Uses the test user's JWT token for authentication.
    Sets the correct team_id for the user's tenant.
    """
    from smartmemory_client import SmartMemoryClient

    client = SmartMemoryClient(
        base_url=service_url,
        token=test_user["access_token"],
        team_id=test_user["team_id"],
    )

    yield client


@pytest.fixture
def unique_content():
    """Generate unique content for test isolation."""
    return f"Test content {uuid.uuid4().hex[:8]}"
