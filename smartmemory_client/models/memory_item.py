from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List


@dataclass
class MemoryItem:
    """
    Client-side representation of a MemoryItem.

    Designed to match the core smartmemory.models.MemoryItem interface
    for portable code between core library and client.

    Supports both attribute access and dict-like access:
        item.content      # attribute
        item["content"]   # dict-like
    """

    item_id: str
    content: str
    memory_type: str = "semantic"
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    embedding: Optional[List[float]] = None

    # Tenancy fields from core MemoryItem
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # Bi-temporal fields (aligned with core SDK)
    valid_start_time: Optional[str] = None  # ISO format datetime
    valid_end_time: Optional[str] = None  # ISO format datetime
    transaction_time: Optional[str] = None  # ISO format datetime

    # Extracted data (populated by ingestion pipeline)
    entities: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None

    # CORE-ORIGIN-1 — tier-aware provenance string set on the server (`api:add`,
    # `evolver:episodic_to_semantic`, etc.). Mirrored from the API response.
    origin: Optional[str] = None

    # CORE-RECALL-LINEAGE-1 — canonical item_ids this item derives from.
    # Always populated on `/memory/search` results (self-reference `[item_id]`
    # for canonicals; K entries for K-source derivations). Empty list on other
    # endpoints that don't run the walker.
    lineage_roots: List[str] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        """Dict-like access for compatibility."""
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Dict-like assignment for compatibility."""
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like get with default."""
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        """
        Create MemoryItem from API response dict.

        Handles various field name conventions from the service.
        """
        # Handle id vs item_id
        item_id = data.get("item_id") or data.get("id") or ""

        return cls(
            item_id=item_id,
            content=data.get("content", ""),
            memory_type=data.get("memory_type", data.get("type", "semantic")),
            metadata=data.get("metadata", {}),
            score=data.get("score"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            embedding=data.get("embedding"),
            user_id=data.get("user_id"),
            workspace_id=data.get("workspace_id"),
            tenant_id=data.get("tenant_id"),
            tags=data.get("tags", []),
            # Bi-temporal fields
            valid_start_time=data.get("valid_start_time"),
            valid_end_time=data.get("valid_end_time"),
            transaction_time=data.get("transaction_time"),
            # Extracted data
            entities=data.get("entities"),
            relations=data.get("relations"),
            # CORE-ORIGIN-1 / CORE-RECALL-LINEAGE-1
            origin=data.get("origin"),
            lineage_roots=list(data.get("lineage_roots") or []),
        )

    def __repr__(self) -> str:
        content_preview = (
            self.content[:50] + "..." if len(self.content) > 50 else self.content
        )
        return f"MemoryItem(item_id='{self.item_id}', content='{content_preview}', type='{self.memory_type}')"
