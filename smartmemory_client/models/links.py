"""Link rows of a memory's neighbors and a decision's provenance (BUG-SUPERSEDE-ISOLATES-REPLACEMENT-1).

Contract: ``smart-memory-docs/docs/features/BUG-SUPERSEDE-ISOLATES-REPLACEMENT-1/inherited-links-contract.json``.
A decision that replaced another keeps the original's links: subject links are copied onto it (its own rows,
``inherited`` false), every other link of the original is inherited on read (``inherited`` true, ``inherited_from``
names the replaced decision that holds it). Typing only: the client returns the service's JSON as dicts.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, TypedDict

LinkClass = Literal["subject", "support", "chain", "infra", "other"]


class NeighborRow(TypedDict, total=False):
    """One row of ``GET /memory/{item_id}/neighbors`` (``SmartMemoryClient.get_neighbors``)."""

    item_id: str
    content: Optional[str]
    memory_type: str
    node_category: str
    entity_name: Optional[str]
    link_type: str
    direction: Literal["outgoing", "incoming"]
    link_class: LinkClass
    inherited: bool
    inherited_from: Optional[str]
    inherited_depth: Optional[int]
    status: Optional[str]  # only on a decision's replaces row (``link_class`` ``chain``)


class InheritedLink(TypedDict, total=False):
    """One entry of a decision provenance's ``inherited_links`` (``SmartMemoryClient.get_provenance_chain``)."""

    memory: Dict[str, Any]
    memory_id: str
    memory_type: str
    content: Optional[str]
    link_type: str
    direction: Literal["outgoing", "incoming"]
    link_class: LinkClass
    role: Optional[str]
    inherited: Literal[True]
    inherited_from: str
    inherited_depth: int


__all__ = ["InheritedLink", "LinkClass", "NeighborRow"]
