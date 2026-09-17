"""
SmartMemory Python Client

Official Python client for the SmartMemory Service API.

Installation:
    pip install smartmemory-client

Usage:
    from smartmemory_client import SmartMemoryClient

    client = SmartMemoryClient(
        base_url="http://localhost:9001",
        api_key="your_jwt_token"
    )

    # Add memory
    item_id = client.add("Test memory")

    # Search
    results = client.search("test", top_k=5)

    # Ingest
    result = client.ingest(
        content="Complex content",
        extractor_name="llm",
        context={"key": "value"}
    )

For more information:
    https://github.com/smartmemory/smart-memory-client
    https://docs.smartmemory.dev
"""

from smartmemory_client.client import (
    RemoteCallTiming,
    SmartMemoryClient,
    SmartMemoryClientError,
    SmartMemoryNotFoundError,
    SmartMemoryPermissionError,
    SmartMemoryValidationError,
    SmartMemoryServerError,
)
from smartmemory_client.models import (
    ConversationContextModel,
    MemoryItem,
    SessionResponse,
)

try:
    from importlib.metadata import version, PackageNotFoundError

    try:
        __version__ = version("smartmemory-client")
    except PackageNotFoundError:
        # Package not installed, try reading VERSION file (development mode)
        from pathlib import Path

        version_file = Path(__file__).parent.parent / "VERSION"
        try:
            __version__ = version_file.read_text().strip()
        except FileNotFoundError:
            __version__ = "0.0.0-dev"
except ImportError:
    __version__ = "0.0.0-dev"

__all__ = [
    "RemoteCallTiming",
    "SmartMemoryClient",
    "SmartMemoryClientError",
    "SmartMemoryNotFoundError",
    "SmartMemoryPermissionError",
    "SmartMemoryValidationError",
    "SmartMemoryServerError",
    "MemoryItem",
    "ConversationContextModel",
    "SessionResponse",
    "__version__",
]
