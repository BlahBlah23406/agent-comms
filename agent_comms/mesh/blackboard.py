"""
Synchronized Cognitive Blackboard (Dual-Brain Mesh)
===================================================
Enables autonomous agents across separate computers to share a single
unified mental model, synchronize beliefs, negotiate contracts symmetrically,
and adapt in real-time as co-equal hemispheres of a single mind.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agent_comms.relay.client import AgentRelayClient
from agent_comms.models.protocol import RelayFrame

logger = logging.getLogger("agent_comms.mesh.blackboard")


class CognitiveBlackboard:
    """
    A distributed, replicated cognitive blackboard shared across agents
    via the AHRP real-time relay mesh.
    """

    def __init__(self, relay_client: AgentRelayClient, topic: str = "mesh.cognitive_sync"):
        self.client = relay_client
        self.topic = topic

        # Replicated mental model state
        self.shared_facts: Dict[str, Any] = {}
        self.locked_contracts: Dict[str, Any] = {}
        self.task_matrix: Dict[str, str] = {}
        self.hypotheses: Dict[str, str] = {}

        # Sync listeners
        self._belief_listeners: List[Callable[[str, Any, str], Coroutine[Any, Any, None]]] = []
        self._contract_listeners: List[Callable[[str, Any, str], Coroutine[Any, Any, None]]] = []
        self._initialized: bool = False

    async def initialize(self):
        """Subscribes to the cognitive sync channel."""
        if not self._initialized:
            await self.client.subscribe(self.topic, self._handle_cognitive_frame)
            self._initialized = True
            logger.info("CognitiveBlackboard initialized on topic '%s' for agent '%s'", self.topic, self.client.agent_id)

    async def set_shared_belief(self, key: str, value: Any, rationale: Optional[str] = None):
        """
        Asserts a new fact or belief into the shared mind and broadcasts
        the cognitive delta to peer agents across the network.
        """
        self.shared_facts[key] = value
        payload = {
            "type": "COGNITIVE_DELTA",
            "operation": "SET_BELIEF",
            "key": key,
            "value": value,
            "rationale": rationale,
            "origin_agent": self.client.agent_id,
            "origin_machine": self.client.machine_id,
        }
        await self.client.publish(self.topic, payload)
        logger.debug("Asserted shared belief '%s' = %s (rationale: %s)", key, value, rationale)

    def get_shared_belief(self, key: str, default: Any = None) -> Any:
        """Retrieves a belief or fact from the local replica of the shared mind."""
        return self.shared_facts.get(key, default)

    def get_all_beliefs(self) -> Dict[str, Any]:
        """Returns a snapshot of all active shared beliefs."""
        return dict(self.shared_facts)

    async def propose_contract(self, contract_name: str, schema: Dict[str, Any]):
        """Proposes an interface contract for symmetric peer negotiation."""
        payload = {
            "type": "CONTRACT_PROPOSAL",
            "contract_name": contract_name,
            "schema": schema,
            "origin_agent": self.client.agent_id,
        }
        await self.client.publish(self.topic, payload)
        logger.info("Proposed contract '%s'", contract_name)

    async def lock_contract(self, contract_name: str, finalized_schema: Dict[str, Any]):
        """Locks an agreed interface contract into the shared blackboard."""
        self.locked_contracts[contract_name] = finalized_schema
        payload = {
            "type": "CONTRACT_LOCKED",
            "contract_name": contract_name,
            "schema": finalized_schema,
            "origin_agent": self.client.agent_id,
        }
        await self.client.publish(self.topic, payload)
        logger.info("Locked contract '%s' with consensus", contract_name)

    def get_contract(self, contract_name: str) -> Optional[Dict[str, Any]]:
        """Returns a locked contract schema if present."""
        return self.locked_contracts.get(contract_name)

    def on_belief_sync(self, callback: Callable[[str, Any, str], Coroutine[Any, Any, None]]):
        """Registers a coroutine callback when a peer agent updates a shared belief: callback(key, value, rationale)."""
        self._belief_listeners.append(callback)

    def on_contract_event(self, callback: Callable[[str, Any, str], Coroutine[Any, Any, None]]):
        """Registers a coroutine callback when contract events occur: callback(contract_name, schema, event_type)."""
        self._contract_listeners.append(callback)

    async def _handle_cognitive_frame(self, frame: RelayFrame):
        payload = frame.payload
        sender = frame.sender_id

        # Ignore self-broadcasts
        if sender == self.client.agent_id:
            return

        frame_type = payload.get("type")
        logger.debug("[%s Blackboard] Received frame '%s' from %s", self.client.agent_id, frame_type, sender)

        if frame_type == "COGNITIVE_DELTA":
            key = payload.get("key")
            value = payload.get("value")
            rationale = payload.get("rationale", "")
            self.shared_facts[key] = value
            for cb in self._belief_listeners:
                try:
                    await cb(key, value, rationale)
                except Exception as e:
                    logger.error("[%s] Error in belief callback: %s", self.client.agent_id, e)

        elif frame_type in ("CONTRACT_PROPOSAL", "CONTRACT_LOCKED"):
            c_name = payload.get("contract_name")
            schema = payload.get("schema")
            if frame_type == "CONTRACT_LOCKED":
                self.locked_contracts[c_name] = schema

            for cb in self._contract_listeners:
                try:
                    await cb(c_name, schema, frame_type)
                except Exception as e:
                    logger.error("[%s] Error in contract callback: %s", self.client.agent_id, e)
