"""
Agent Comms Cross-Session & Instant Discovery Package
"""

from agent_comms.session.discovery import (
    DEFAULT_DISCOVERY_PORT,
    DiscoveredPeer,
    UDPDiscoveryBroadcaster,
    UDPDiscoveryListener,
    get_local_ip,
)
from agent_comms.session.manager import ActiveCrossSession, CrossSessionManager
from agent_comms.session.standby import StandbyNode

__all__ = [
    "DEFAULT_DISCOVERY_PORT",
    "DiscoveredPeer",
    "UDPDiscoveryBroadcaster",
    "UDPDiscoveryListener",
    "get_local_ip",
    "ActiveCrossSession",
    "CrossSessionManager",
    "StandbyNode",
]
