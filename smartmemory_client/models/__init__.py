"""
SmartMemory Client Models

Pydantic-style dataclass models for type-safe API interactions.
"""

from smartmemory_client.models.memory_item import MemoryItem
from smartmemory_client.models.conversation import ConversationContextModel
from smartmemory_client.models.session import SessionResponse
from smartmemory_client.models.routing import (
    RoutingCandidate,
    RoutingEcho,
    RoutingExplain,
    RoutingNotice,
    RoutingPrefs,
    routing_echo,
)

__all__ = [
    "MemoryItem",
    "ConversationContextModel",
    "SessionResponse",
    "RoutingCandidate",
    "RoutingEcho",
    "RoutingExplain",
    "RoutingNotice",
    "RoutingPrefs",
    "routing_echo",
]
