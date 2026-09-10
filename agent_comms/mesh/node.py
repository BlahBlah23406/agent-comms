"""
Dual-Brain Peer Node
====================
Provides a high-level, production-ready interface for an autonomous agent
to join a distributed dual-brain mesh, synchronize mental models with peers,
and export synchronized twin Context Capsules.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agent_comms.relay.client import AgentRelayClient
from agent_comms.mesh.blackboard import CognitiveBlackboard
from agent_comms.capsule.packager import CapsulePackager
from agent_comms.models.capsule import ContextCapsule, EpistemicLearning

logger = logging.getLogger("agent_comms.mesh.node")


class DualBrainNode:
    """
    High-level agent node for the Dual-Brain mesh.
    Operates as a co-equal hemisphere of a distributed mind across computers.
    """

    def __init__(
        self,
        agent_id: str,
        relay_url: str = "ws://localhost:8765/ws",
        machine_id: Optional[str] = None,
        role: str = "mesh-peer",
        capabilities: Optional[List[str]] = None,
        cognitive_topic: str = "mesh.cognitive_sync",
    ):
        self.agent_id = agent_id
        self.relay_url = relay_url
        self.machine_id = machine_id or socket.gethostname()
        self.role = role
        self.capabilities = capabilities or ["p2p_mesh", "cognitive_blackboard"]
        self.cognitive_topic = cognitive_topic

        self.relay = AgentRelayClient(
            relay_url=self.relay_url,
            agent_id=self.agent_id,
            machine_id=self.machine_id,
            capabilities=self.capabilities,
        )
        self.blackboard = CognitiveBlackboard(self.relay, topic=self.cognitive_topic)
        self._is_started: bool = False

    async def start(self):
        """Connects to the AHRP relay and activates the cognitive blackboard."""
        if not self._is_started:
            await self.relay.connect()
            await self.blackboard.initialize()
            self._is_started = True
            logger.info("DualBrainNode '%s' started on machine '%s'", self.agent_id, self.machine_id)

    async def stop(self):
        """Gracefully disconnects from the mesh."""
        if self._is_started:
            await self.relay.disconnect()
            self._is_started = False
            logger.info("DualBrainNode '%s' stopped", self.agent_id)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    # Blackboard convenience wrappers
    async def set_belief(self, key: str, value: Any, rationale: Optional[str] = None):
        """Asserts a fact into the shared mind and broadcasts the delta to peers."""
        await self.blackboard.set_shared_belief(key, value, rationale=rationale)

    def get_belief(self, key: str, default: Any = None) -> Any:
        """Reads a fact from the local replica of the shared mind."""
        return self.blackboard.get_shared_belief(key, default)

    def get_all_beliefs(self) -> Dict[str, Any]:
        """Returns all shared beliefs."""
        return self.blackboard.get_all_beliefs()

    async def propose_contract(self, name: str, schema: Dict[str, Any]):
        """Proposes an interface contract for symmetric negotiation."""
        await self.blackboard.propose_contract(name, schema)

    async def lock_contract(self, name: str, schema: Dict[str, Any]):
        """Locks an agreed interface contract into the blackboard."""
        await self.blackboard.lock_contract(name, schema)

    def on_belief_update(self, callback: Callable[[str, Any, str], Coroutine[Any, Any, None]]):
        """Subscribes a callback to cognitive deltas from peer agents: callback(key, value, rationale)."""
        self.blackboard.on_belief_sync(callback)

    def on_contract_event(self, callback: Callable[[str, Any, str], Coroutine[Any, Any, None]]):
        """Subscribes a callback to contract events: callback(name, schema, event_type)."""
        self.blackboard.on_contract_event(callback)

    # Context Capsule persistence
    def export_twin_capsule(
        self,
        task_id: str,
        summary: str,
        next_steps: Optional[List[str]] = None,
        additional_learnings: Optional[List[EpistemicLearning]] = None,
        repo_path: Optional[str] = None,
    ) -> ContextCapsule:
        """
        Creates a synchronized Context Capsule from the shared mental model,
        local machine context, and git working directory state.
        """
        from pathlib import Path
        from agent_comms.models.capsule import LearningCategory

        learnings: List[EpistemicLearning] = []

        # Convert shared blackboard facts into epistemic learnings
        for key, val in self.blackboard.get_all_beliefs().items():
            learnings.append(
                EpistemicLearning(
                    category=LearningCategory.FINDING,
                    summary=f"Shared belief '{key}': {val}",
                    evidence=f"Asserted to CognitiveBlackboard on {self.machine_id}",
                )
            )

        if additional_learnings:
            learnings.extend(additional_learnings)

        # Include locked contracts
        for c_name, c_schema in self.blackboard.locked_contracts.items():
            learnings.append(
                EpistemicLearning(
                    category=LearningCategory.FINDING,
                    summary=f"Consensus contract '{c_name}' locked",
                    details=str(c_schema),
                )
            )

        packager = CapsulePackager(workspace_path=Path(repo_path) if repo_path else None)
        capsule = packager.package(
            task_id=task_id,
            title=task_id,
            executive_summary=summary,
            goal=summary,
            next_action=next_steps[0] if next_steps else "Continue peer execution",
            epistemic_learnings=learnings,
            agent_name=self.agent_id,
        )
        return capsule
