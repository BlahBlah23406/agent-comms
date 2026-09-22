"""
Standby Node Daemon
===================
Runs quietly on a secondary machine (desktop, GPU workstation, cloud VM).
Awaits activation signals from peer machines over LAN broadcast (UDP) or Live Relay.
Upon activation, automatically receives code/context capsules, restores workspace,
and joins the real-time cross-machine collaborative session with zero manual friction.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.config import config_manager
from agent_comms.mesh.node import DualBrainNode
from agent_comms.models.capsule import ContextCapsule
from agent_comms.models.protocol import FrameType, RelayFrame
from agent_comms.relay.client import AgentRelayClient
from agent_comms.session.discovery import DEFAULT_DISCOVERY_PORT, UDPDiscoveryListener, get_local_ip

logger = logging.getLogger("agent_comms.session.standby")


class StandbyNode:
    """
    Background standby agent node.
    Listens on LAN UDP and optionally connects to a background relay client.
    When an activation signal is received, spins up active collaboration.
    """

    def __init__(
        self,
        machine_alias: Optional[str] = None,
        discovery_port: Optional[int] = None,
        relay_url: Optional[str] = None,
        workspace_path: Optional[Path] = None,
        auto_unpack_capsules: bool = True,
        on_active_session: Optional[Callable[[DualBrainNode, Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
    ):
        self.machine_alias = machine_alias or config_manager.get("machine_alias", socket.gethostname())
        self.discovery_port = discovery_port or config_manager.get("discovery_port", DEFAULT_DISCOVERY_PORT)
        self.default_relay_url = relay_url or config_manager.get("default_relay_url", "ws://localhost:8765/ws")
        self.workspace_path = (workspace_path or Path.cwd()).resolve()
        self.auto_unpack = auto_unpack_capsules
        self.on_active_session = on_active_session

        self.store = CapsuleStore()
        self.unpacker = CapsuleUnpacker(workspace_path=self.workspace_path)

        # Discovery listener
        self._listener: Optional[UDPDiscoveryListener] = None
        # Relay client for remote standby
        self._relay_client: Optional[AgentRelayClient] = None
        # Active session node
        self.active_node: Optional[DualBrainNode] = None
        self._is_active = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Starts standby listening on LAN and connects standby relay client if available."""
        logger.info("Starting StandbyNode '%s' on %s...", self.machine_alias, get_local_ip())

        # 1. Start LAN discovery listener
        self._listener = UDPDiscoveryListener(
            machine_alias=self.machine_alias,
            port=self.discovery_port,
            capabilities=["agent_comms", "dual_brain", "standby_worker"],
            on_wake=self._handle_lan_wake,
        )
        self._listener.start()

        # 2. Start standby relay client if configured
        try:
            self._relay_client = AgentRelayClient(
                agent_id=f"standby-{self.machine_alias}",
                relay_url=self.default_relay_url,
                machine_id=self.machine_alias,
                capabilities=["standby_worker"],
            )
            self._relay_client.on_activation(self._handle_relay_activation)
            await self._relay_client.connect()
            logger.info("Connected standby agent to relay %s", self.default_relay_url)
        except Exception as e:
            logger.debug("Relay hub not immediately reachable for standby (%s); relying on LAN wake-up", e)

        # 3. Start background Preemptive Quota Watchdog
        try:
            from agent_comms.quota.watchdog import SessionWatchdog
            self._watchdog = SessionWatchdog(config=self.config)
            self._watchdog.start()
            print("[*] Preemptive Quota Guard: Active Watchdog monitoring Claude & AGY sessions")
        except Exception as e:
            logger.debug("Could not start SessionWatchdog in standby: %s", e)

        print(f"\n[*] Agent Comms Standby Node Active: '{self.machine_alias}'")
        print(f"[*] Local IP: {get_local_ip()} | Listening for LAN auto-wake on UDP:{self.discovery_port}")
        print(f"[*] Workspace: {self.workspace_path}")
        print("[+] Ready and awaiting activation from peer machines...\n")

    async def stop(self):
        """Stops standby listener, watchdog, and any active session."""
        if hasattr(self, "_watchdog") and self._watchdog:
            self._watchdog.stop()
        if self._listener:
            self._listener.stop()
        if self._relay_client:
            await self._relay_client.disconnect()
        if self.active_node:
            await self.active_node.stop()
        self._shutdown_event.set()
        logger.info("StandbyNode '%s' stopped", self.machine_alias)

    async def run_until_interrupted(self):
        """Keeps standby process running until cancelled."""
        await self.start()
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def _handle_lan_wake(self, packet: Dict[str, Any], addr: tuple):
        """Triggered when a WAKE_ACTIVATE packet arrives over LAN."""
        session_id = packet.get("session_id", "default-session")
        relay_url = packet.get("relay_url")
        capsule_data = packet.get("capsule")
        capsule_id = packet.get("capsule_id")

        print(f"\n[!] WAKE SIGNAL RECEIVED from {addr[0]} for session '{session_id}'!")
        await self.activate(
            session_id=session_id,
            relay_url=relay_url,
            capsule_data=capsule_data,
            capsule_id=capsule_id,
        )

    async def _handle_relay_activation(self, frame: RelayFrame):
        """Triggered when an ACTIVATE_SESSION frame arrives over Relay."""
        payload = frame.payload
        session_id = payload.get("session_id", "default-session")
        relay_url = payload.get("relay_url") or self.default_relay_url
        capsule_data = payload.get("capsule")
        capsule_id = payload.get("capsule_id") or payload.get("task_id")

        print(f"\n[!] WAKE SIGNAL RECEIVED via Relay from '{frame.sender_id}' for session '{session_id}'!")
        await self.activate(
            session_id=session_id,
            relay_url=relay_url,
            capsule_data=capsule_data,
            capsule_id=capsule_id,
            initiator_id=frame.sender_id,
        )

    async def activate(
        self,
        session_id: str,
        relay_url: Optional[str] = None,
        capsule_data: Optional[Dict[str, Any]] = None,
        capsule_id: Optional[str] = None,
        initiator_id: Optional[str] = None,
    ):
        """
        Wakes up the node, restores workspace context if capsule provided,
        and connects to the live cross-session mesh.
        """
        if self._is_active and getattr(self, "_active_session_id", None) == session_id:
            logger.info("Session '%s' is already active on this node. Ignoring duplicate activation.", session_id)
            return

        self._active_session_id = session_id
        effective_relay = relay_url or self.default_relay_url
        print(f"[+] Activating collaborative agent on session '{session_id}'...")
        print(f"[+] Connecting to session relay: {effective_relay}")

        # 1. Restore capsule if provided or fetch if capsule_id specified
        if not capsule_data and capsule_id:
            local_cap = self.store.load_by_id(capsule_id)
            if local_cap:
                capsule_data = local_cap.model_dump()
            elif effective_relay:
                try:
                    from agent_comms.capsule.cloud.relay import RelayCloudProvider
                    provider = RelayCloudProvider(relay_url=effective_relay)
                    fetched_cap = await asyncio.to_thread(provider.download, capsule_id)
                    capsule_data = fetched_cap.model_dump()
                except Exception as e:
                    logger.debug("Could not fetch capsule '%s' from relay: %s", capsule_id, e)

        if capsule_data and self.auto_unpack:
            try:
                capsule = ContextCapsule.model_validate(capsule_data)
                self.store.save(capsule)
                unpacked = self.unpacker.apply(capsule, apply_workspace=True)
                print(f"[+] Auto-restored Context Capsule: {capsule.capsule_id} ({capsule.task_id})")
                print(f"[+] Patch status: {unpacked['git_patch_message']}")
                if unpacked["untracked_files_restored"]:
                    print(f"[+] Restored files: {', '.join(unpacked['untracked_files_restored'])}")
            except Exception as e:
                print(f"[!] Warning restoring capsule: {e}")

        # 2. Instantiate and connect DualBrainNode
        if self.active_node:
            await self.active_node.stop()

        self.active_node = DualBrainNode(
            agent_id=f"agent-{self.machine_alias}",
            relay_url=effective_relay,
            machine_id=self.machine_alias,
            role="cross-session-peer",
            cognitive_topic=f"session.{session_id}.cognitive",
        )
        await self.active_node.start()

        # Listen for any live capsule transfers sent over the WebSocket mesh
        async def _on_live_capsule(frame: RelayFrame):
            c_dict = frame.payload.get("capsule")
            if c_dict and self.auto_unpack:
                try:
                    c = ContextCapsule.model_validate(c_dict)
                    self.store.save(c)
                    self.unpacker.apply(c, apply_workspace=True)
                    print(f"[+] Auto-unpacked live capsule transfer: {c.capsule_id}")
                except Exception as ex:
                    logger.debug("Live capsule unpack error: %s", ex)

        self.active_node.relay.on_capsule_transfer(_on_live_capsule)
        self._is_active = True

        # 3. Confirm activation to initiator
        if initiator_id and self._relay_client:
            try:
                await self._relay_client.confirm_activated(
                    target_id=initiator_id,
                    session_id=session_id,
                    status="ready",
                    details={"machine_alias": self.machine_alias, "ip": get_local_ip()},
                )
            except Exception:
                pass

        print(f"[+] Machine '{self.machine_alias}' is now LIVE in active cross-session '{session_id}'!")

        # 4. Trigger optional custom runner callback
        if self.on_active_session:
            asyncio.create_task(
                self.on_active_session(
                    self.active_node,
                    {"session_id": session_id, "relay_url": effective_relay, "capsule": capsule_data},
                )
            )
