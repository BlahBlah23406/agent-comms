"""
Synchronized Cognitive Blackboard (Dual-Brain Mesh)
===================================================
Enables two autonomous agents across separate computers to share a single
unified mental model, synchronize beliefs, negotiate contracts symmetrically,
and adapt in real-time as two hemispheres of a single mind.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional
from agent_comms.relay.client import AgentRelayClient
from agent_comms.models.protocol import RelayFrame

logger = logging.getLogger("agent_comms.p2p.blackboard")


class CognitiveBlackboard:
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

    async def initialize(self):
        """Subscribes to the cognitive sync channel."""
        await self.client.subscribe(self.topic, self._handle_cognitive_frame)

    async def set_shared_belief(self, key: str, value: Any, rationale: Optional[str] = None):
        """
        Asserts a new fact or belief into the shared mind and broadcasts
        the cognitive delta to the peer agent on the other computer.
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

    async def propose_contract(self, contract_name: str, schema: Dict[str, Any]):
        """Proposes an interface contract for symmetric negotiation."""
        payload = {
            "type": "CONTRACT_PROPOSAL",
            "contract_name": contract_name,
            "schema": schema,
            "origin_agent": self.client.agent_id,
        }
        await self.client.publish(self.topic, payload)

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

    def on_belief_sync(self, callback: Callable[[str, Any, str], Coroutine[Any, Any, None]]):
        """Registers a callback when the peer agent updates a shared belief."""
        self._belief_listeners.append(callback)

    def on_contract_event(self, callback: Callable[[str, Any, str], Coroutine[Any, Any, None]]):
        """Registers a callback when contract events occur."""
        self._contract_listeners.append(callback)

    async def _handle_cognitive_frame(self, frame: RelayFrame):
        payload = frame.payload
        sender = frame.sender_id

        # Don't echo self updates
        if sender == self.client.agent_id:
            return

        frame_type = payload.get("type")
        print(f"[{self.client.agent_id} CognitiveBlackboard] Received frame '{frame_type}' from {sender}", flush=True)

        if frame_type == "COGNITIVE_DELTA":
            key = payload.get("key")
            value = payload.get("value")
            rationale = payload.get("rationale")
            self.shared_facts[key] = value
            for cb in self._belief_listeners:
                try:
                    await cb(key, value, rationale or "")
                except Exception as e:
                    print(f"[{self.client.agent_id}] Error in belief callback: {e}", flush=True)

        elif frame_type in ("CONTRACT_PROPOSAL", "CONTRACT_LOCKED"):
            c_name = payload.get("contract_name")
            schema = payload.get("schema")
            if frame_type == "CONTRACT_LOCKED":
                self.locked_contracts[c_name] = schema
            print(f"[{self.client.agent_id} CognitiveBlackboard] Dispathing {frame_type} to {len(self._contract_listeners)} listeners", flush=True)
            for cb in self._contract_listeners:
                try:
                    await cb(c_name, schema, frame_type)
                except Exception as e:
                    print(f"[{self.client.agent_id}] Error in contract callback: {e}", flush=True)
