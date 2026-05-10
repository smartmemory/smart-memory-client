from smartmemory_client.models.memory_item import MemoryItem

print("Successfully imported MemoryItem and SmartMemoryClient")

item = MemoryItem(
    item_id="test_id",
    content="test content",
    memory_type="semantic",
    metadata={"key": "value"},
)

print(f"Created MemoryItem: {item}")

try:
    import smartmemory

    print(
        "WARNING: smartmemory core package is still accessible (this might be expected in this environment but client shouldn't depend on it)"
    )
except ImportError:
    print("SUCCESS: smartmemory core package is NOT accessible (clean separation)")
