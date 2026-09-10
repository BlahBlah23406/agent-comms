"""
Agent Comms Mesh Module
=======================
Peer-to-peer dual-brain synchronization, replicated cognitive blackboard,
and distributed multi-machine coordination.
"""

from agent_comms.mesh.blackboard import CognitiveBlackboard
from agent_comms.mesh.node import DualBrainNode

__all__ = ["CognitiveBlackboard", "DualBrainNode"]
