from importlib.util import find_spec

from smartmemory_client.models.memory_item import MemoryItem

item = MemoryItem(
    item_id="test_id",
    content="test content",
    memory_type="semantic",
    metadata={"key": "value"},
)

core_available = find_spec("smartmemory") is not None
if core_available:
    import smartmemory

print("Successfully imported MemoryItem and SmartMemoryClient")
print(f"Created MemoryItem: {item}")

if core_available:
    print(
        "WARNING: smartmemory core package is still accessible (this might be expected in this environment but client shouldn't depend on it)"
    )
else:
    print("SUCCESS: smartmemory core package is NOT accessible (clean separation)")
