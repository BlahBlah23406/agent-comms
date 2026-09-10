"""
Agent Comms: Universal Cross-Agent, Cross-Machine Handover & Live Relay Suite
"""

__version__ = "1.0.0"

from agent_comms.models.capsule import ContextCapsule, EpistemicLearning, TaskGraph, TaskStep
from agent_comms.models.protocol import RelayFrame, AgentDescriptor
from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.capsule.store import CapsuleStore
from agent_comms.relay.client import AgentRelayClient
from agent_comms.relay.server import RelayHub, create_app
from agent_comms.mesh.blackboard import CognitiveBlackboard
from agent_comms.mesh.node import DualBrainNode

__all__ = [
    "ContextCapsule",
    "EpistemicLearning",
    "TaskGraph",
    "TaskStep",
    "RelayFrame",
    "AgentDescriptor",
    "CapsulePackager",
    "CapsuleUnpacker",
    "CapsuleStore",
    "AgentRelayClient",
    "RelayHub",
    "create_app",
    "CognitiveBlackboard",
    "DualBrainNode",
]
