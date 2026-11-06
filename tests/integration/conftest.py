"""Auto-mark all tests in this directory as integration tests."""

import pathlib

import pytest

_THIS_DIR = pathlib.Path(__file__).parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        if pathlib.Path(item.fspath).is_relative_to(_THIS_DIR):
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def saved_receipts(authenticated_client):
    """Delete exact saved handles even when an assertion or fixture setup fails."""
    from smartmemory_client import SmartMemoryNotFoundError

    receipts = []
    yield receipts
    failures = []
    for receipt in reversed(receipts):
        try:
            authenticated_client.delete(receipt.item_id)
        except SmartMemoryNotFoundError:
            pass  # The lifecycle test may already have deleted this exact item.
        except Exception as error:
            failures.append((receipt.item_id, type(error).__name__))
    assert not failures, f"Saved-item cleanup failed: {failures}"
