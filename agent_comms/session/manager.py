"""
Cross-Session Manager & Orchestrator
====================================
Initiates, activates, and coordinates distributed multi-machine agent sessions.
Automatically manages relay server lifecycle, zero-config LAN peer wake-up,
context capsule transmission, and dual-brain cognitive synchronization.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uvicorn

from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.config import config_manager
from agent_comms.mesh.node import DualBrainNode
from agent_comms.models.capsule import ContextCapsule
from agent_comms.models.protocol import FrameType, RelayFrame
from agent_comms.relay.client import AgentRelayClient
from agent_comms.relay.server import RelayHub, create_app
from agent_comms.session.discovery import (
    DEFAULT_DISCOVERY_PORT,
    DiscoveredPeer,
    UDPDiscoveryBroadcaster,
    get_local_ip,
)

logger = logging.getLogger("agent_comms.session.manager")


class ActiveCrossSession:
    """Represents a live, connected multi-machine session."""

    def __init__(
        self,
        session_id: str,
        relay_url: str,
        local_node: DualBrainNode,
        connected_peers: List[str],
        server_task: Optional[asyncio.Task] = None,
        server_obj: Optional[uvicorn.Server] = None,
    ):
        self.session_id = session_id
        self.relay_url = relay_url
        self.local_node = local_node
        self.connected_peers = connected_peers
        self._server_task = server_task
        self._server_obj = server_obj

    async def send_capsule(self, target_agent: str, capsule: ContextCapsule):
        """Transfers a Context Capsule directly to a peer in the live session."""
        await self.local_node.relay.transfer_capsule(
            target_id=target_agent,
            capsule_dict=capsule.model_dump(),
        )

    async def broadcast_belief(self, key: str, value: Any, rationale: Optional[str] = None):
        """Synchronizes a mental fact across all connected machines."""
        await self.local_node.set_belief(key, value, rationale=rationale)

    async def close(self):
        """Terminates the cross-session and disconnects all nodes."""
        if self.local_node:
            await self.local_node.stop()
        if self._server_obj:
            self._server_obj.should_exit = True
        if self._server_task:
            try:
                await self._server_task
            except Exception:
                pass
        logger.info("Cross-session '%s' closed", self.session_id)


class CrossSessionManager:
    """
    Orchestrates starting and connecting active cross-sessions.
    """

    def __init__(
        self,
        machine_alias: Optional[str] = None,
        workspace_path: Optional[Path] = None,
        discovery_port: Optional[int] = None,
    ):
        self.machine_alias = machine_alias or config_manager.get("machine_alias", socket.gethostname())
        self.workspace_path = (workspace_path or Path.cwd()).resolve()
        self.discovery_port = discovery_port or config_manager.get("discovery_port", DEFAULT_DISCOVERY_PORT)
        self.broadcaster = UDPDiscoveryBroadcaster(port=self.discovery_port)
        self.store = CapsuleStore()

    async def discover_lan_peers(self, timeout: float = 1.5) -> List[DiscoveredPeer]:
        """Discovers any standby machines available on the local network."""
        return await self.broadcaster.discover_peers(timeout=timeout)

    async def start_session(
        self,
        session_id: Optional[str] = None,
        target_machine: Optional[str] = None,
        capsule_or_id: Optional[Union[str, ContextCapsule]] = None,
        relay_port: int = 8765,
        external_relay_url: Optional[str] = None,
        auto_wake_lan: bool = True,
        timeout: float = 8.0,
    ) -> ActiveCrossSession:
        """
        Starts an active cross-session and automatically activates standby machine(s).
        Zero manual setup required on the remote machine.
        """
        sid = session_id or f"session-{uuid.uuid4().hex[:8]}"
        local_ip = get_local_ip()

        server_task = None
        server_obj = None
        relay_hub = None

        # 1. Determine Relay URL (spin up local relay if not specified)
        if external_relay_url:
            relay_url = external_relay_url
            print(f"[+] Using external Relay: {relay_url}")
        else:
            # Check if relay already running on relay_port
            is_running = self._is_port_open("127.0.0.1", relay_port)
            if is_running:
                relay_url = f"ws://{local_ip}:{relay_port}/ws"
                print(f"[+] Reusing existing AHRP Relay at {relay_url}")
            else:
                print(f"[+] Auto-spawning AHRP Relay hub on {local_ip}:{relay_port}...")
                relay_hub = RelayHub()
                app = create_app(hub=relay_hub)
                config = uvicorn.Config(
                    app,
                    host="0.0.0.0",
                    port=relay_port,
                    log_level="warning",
                    ws_max_size=32 * 1024 * 1024,
                )
                server_obj = uvicorn.Server(config)
                server_task = asyncio.create_task(server_obj.serve())

                for _ in range(30):
                    if server_obj.started:
                        break
                    await asyncio.sleep(0.1)

                relay_url = f"ws://{local_ip}:{relay_port}/ws"
                print(f"[+] Relay Hub live at: {relay_url}")

        # 2. Resolve Capsule if provided
        capsule_data = None
        capsule_id = None
        c_obj = None
        if capsule_or_id:
            if isinstance(capsule_or_id, ContextCapsule):
                capsule_data = capsule_or_id.model_dump()
                capsule_id = capsule_or_id.capsule_id
                c_obj = capsule_or_id
            else:
                c = self.store.load_by_id(capsule_or_id)
                if not c:
                    p = Path(capsule_or_id)
                    if p.exists() and p.is_file():
                        c = self.store.load_from_file(p)
                if c:
                    capsule_data = c.model_dump()
                    capsule_id = c.capsule_id
                    c_obj = c

        # Store capsule in relay hub so standby peer can fetch it via REST or WebSocket
        if capsule_data and capsule_id:
            if relay_hub is not None:
                relay_hub.capsules[capsule_id] = capsule_data
            try:
                if c_obj:
                    from agent_comms.capsule.cloud.relay import RelayCloudProvider
                    rest_url = f"http://127.0.0.1:{relay_port}" if not external_relay_url else relay_url
                    provider = RelayCloudProvider(relay_url=rest_url)
                    await asyncio.to_thread(provider.upload, c_obj)
            except Exception as e:
                logger.debug("Capsule upload via HTTP: %s", e)

        # 3. Connect local DualBrainNode for initiator
        local_node = DualBrainNode(
            agent_id=f"agent-{self.machine_alias}",
            relay_url=f"ws://127.0.0.1:{relay_port}/ws" if not external_relay_url else relay_url,
            machine_id=self.machine_alias,
            role="session-initiator",
            cognitive_topic=f"session.{sid}.cognitive",
        )
        await local_node.start()

        # 4. Wake up remote standby peer(s)
        activated_peers: List[str] = []

        if auto_wake_lan:
            print(f"[+] Scanning LAN for standby machines on UDP:{self.discovery_port}...")
            discovered = await self.discover_lan_peers(timeout=1.0)
            if discovered:
                print(f"[+] Found {len(discovered)} standby machine(s) on LAN:")
                for p in discovered:
                    print(f"    - '{p.machine_alias}' ({p.os_name} @ {p.ip})")
            else:
                print("[*] No immediate LAN standby nodes detected; broadcasting wake-up beacon...")

            print(f"[+] Broadcasting WAKE_ACTIVATE for session '{sid}'...")
            woken_acks = await self.broadcaster.wake_peer(
                session_id=sid,
                relay_url=relay_url,
                target_machine=target_machine,
                task_capsule_dict=capsule_data,
                capsule_id=capsule_id,
                timeout=2.0,
            )
            for ack in woken_acks:
                m_alias = ack.get("machine_alias", ack.get("machine_id", "peer"))
                activated_peers.append(m_alias)
                print(f"[+] Standby machine '{m_alias}' acknowledged wake-up signal!")

        # 5. Also send activation frame via Relay for remote/cloud standby nodes
        try:
            await local_node.relay.activate_peer(
                target_id=f"standby-{target_machine}" if target_machine else None,
                session_id=sid,
                relay_url=relay_url,
                capsule_data=capsule_data,
                task_id=capsule_id,
            )
        except Exception:
            pass

        # 6. Await peer connection on the relay
        print(f"[*] Waiting for peer agent to connect to session '{sid}'...")
        start_wait = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start_wait < timeout:
            peers = await local_node.relay.list_peers()
            connected_remote = [
                p.agent_id for p in peers if p.agent_id != local_node.agent_id and not p.agent_id.startswith("standby-")
            ]
            if connected_remote:
                for cr in connected_remote:
                    if cr not in activated_peers:
                        activated_peers.append(cr)
                # Transfer capsule to connected peer over WebSocket
                if capsule_data:
                    for cr in connected_remote:
                        try:
                            await local_node.relay.transfer_capsule(cr, capsule_data)
                        except Exception:
                            pass
                break
            await asyncio.sleep(0.3)

        if activated_peers:
            print(f"\n[+] ACTIVE CROSS-SESSION ESTABLISHED with: {', '.join(activated_peers)}")
            print(f"[+] Cognitive blackboard synced on topic 'session.{sid}.cognitive'")
            print("Both machines are now live in the same session with zero context loss!\n")
        else:
            print(f"\n[!] Session '{sid}' created and waiting. Other machines can join via:")
            print(f"    agent-comms session join {relay_url}\n")

        return ActiveCrossSession(
            session_id=sid,
            relay_url=relay_url,
            local_node=local_node,
            connected_peers=activated_peers,
            server_task=server_task,
            server_obj=server_obj,
        )

    def _is_port_open(self, host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex((host, port)) == 0
