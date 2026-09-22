"""
LAN Auto-Discovery & Zero-Config Wake-Up Beacon
==============================================
Enables machines on the same local network to discover each other and wake up
standby agent sessions without manually configuring IP addresses or ports.
Uses lightweight UDP broadcast beacons (port 8764 by default).
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("agent_comms.session.discovery")

DEFAULT_DISCOVERY_PORT = 8764


def get_local_ip() -> str:
    """Discovers the active local network IP of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually transmit or require reachability
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


class DiscoveredPeer:
    def __init__(
        self,
        machine_id: str,
        machine_alias: str,
        ip: str,
        port: int,
        os_name: str,
        status: str = "standby",
        capabilities: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.machine_id = machine_id
        self.machine_alias = machine_alias
        self.ip = ip
        self.port = port
        self.os_name = os_name
        self.status = status
        self.capabilities = capabilities or []
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "machine_alias": self.machine_alias,
            "ip": self.ip,
            "port": self.port,
            "os_name": self.os_name,
            "status": self.status,
            "capabilities": self.capabilities,
            "extra": self.extra,
        }

    def __repr__(self) -> str:
        return f"<DiscoveredPeer {self.machine_alias} ({self.ip}:{self.port}) [{self.status}]>"


class UDPDiscoveryListener:
    """
    Runs on standby machines. Listens on UDP broadcast port for:
    1. DISCOVERY_PING -> Responds with DISCOVERY_PONG containing peer info.
    2. WAKE_ACTIVATE  -> Triggers activation callback to start cross-session.
    """

    def __init__(
        self,
        machine_alias: Optional[str] = None,
        port: int = DEFAULT_DISCOVERY_PORT,
        capabilities: Optional[List[str]] = None,
        on_wake: Optional[Callable[[Dict[str, Any], tuple], Coroutine[Any, Any, None]]] = None,
    ):
        self.port = port
        self.machine_id = socket.gethostname()
        self.machine_alias = machine_alias or self.machine_id
        self.os_name = platform.system()
        self.capabilities = capabilities or ["agent_comms", "standby"]
        self.on_wake = on_wake
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self):
        """Initializes the UDP socket and starts listening asynchronously."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow multiple listeners on same port for local simulations
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass

        self._sock.bind(("", self.port))
        self._sock.setblocking(False)
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("UDPDiscoveryListener started on port %d for '%s'", self.port, self.machine_alias)

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        if self._sock:
            self._sock.close()
            self._sock = None

    async def _listen_loop(self):
        # sock_recvfrom() is 3.11+, which is what sets this package's minimum.
        loop = asyncio.get_running_loop()
        while self._running and self._sock:
            try:
                data, addr = await loop.sock_recvfrom(self._sock, 65535)
                if not data:
                    continue
                packet = json.loads(data.decode("utf-8"))
                p_type = packet.get("type")

                # Ignore our own broadcast if matching machine_id and same IP
                if packet.get("machine_id") == self.machine_id and addr[0] == get_local_ip():
                    continue

                if p_type == "DISCOVERY_PING":
                    # Respond with PONG
                    pong = {
                        "type": "DISCOVERY_PONG",
                        "machine_id": self.machine_id,
                        "machine_alias": self.machine_alias,
                        "ip": get_local_ip(),
                        "port": self.port,
                        "os_name": self.os_name,
                        "status": "standby",
                        "capabilities": self.capabilities,
                    }
                    self._sock.sendto(json.dumps(pong).encode("utf-8"), addr)

                elif p_type == "WAKE_ACTIVATE":
                    # Verify target machine match (or broadcast "*")
                    target = packet.get("target_machine")
                    if not target or target in ("*", self.machine_id, self.machine_alias):
                        logger.info("Received WAKE_ACTIVATE from %s for session '%s'", addr, packet.get("session_id"))
                        # Send immediate ACK
                        ack = {
                            "type": "WAKE_ACK",
                            "machine_id": self.machine_id,
                            "machine_alias": self.machine_alias,
                            "status": "activating",
                            "session_id": packet.get("session_id"),
                        }
                        self._sock.sendto(json.dumps(ack).encode("utf-8"), addr)

                        # Trigger wake callback
                        if self.on_wake:
                            asyncio.create_task(self.on_wake(packet, addr))

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.debug("Error in discovery listen loop: %s", e)
                await asyncio.sleep(0.1)


class UDPDiscoveryBroadcaster:
    """
    Runs on the initiating machine. Broadcasts packets over LAN to:
    1. discover_peers(): Discover standby machines on LAN.
    2. wake_peer(): Wake up a remote standby peer or all standby peers.
    """

    def __init__(self, port: int = DEFAULT_DISCOVERY_PORT):
        self.port = port
        self.machine_id = socket.gethostname()

    def _get_destinations(self, target_machine: Optional[str] = None) -> List[tuple]:
        """Collects destination addresses for discovery and wake packets across LAN and mesh peers."""
        dests = [("<broadcast>", self.port), ("127.0.0.1", self.port)]
        candidates = set()
        if target_machine and target_machine != "*":
            candidates.add(target_machine)
            if target_machine.startswith("the-"):
                candidates.add(target_machine[4:])
            else:
                candidates.add(f"the-{target_machine}")

        own_alias = ""
        try:
            from agent_comms.config import ConfigManager
            cfg = ConfigManager()
            own_alias = (cfg.get("machine_alias") or "").lower()
            for p in cfg.get("known_peers", []):
                candidates.add(p)
                if p.startswith("the-"):
                    candidates.add(p[4:])
                else:
                    candidates.add(f"the-{p}")
        except Exception:
            pass

        my_names = {self.machine_id.lower(), socket.gethostname().lower(), own_alias, "localhost"}
        my_ips = {"127.0.0.1", get_local_ip()}

        seen_ips = {"127.0.0.1"}
        for host in candidates:
            if host.lower() in my_names:
                continue
            try:
                resolved_ip = socket.gethostbyname(host)
                if resolved_ip in my_ips or resolved_ip in seen_ips:
                    continue
                seen_ips.add(resolved_ip)
                dests.append((resolved_ip, self.port))
            except Exception:
                dests.append((host, self.port))
        return dests

    async def discover_peers(self, timeout: float = 1.5) -> List[DiscoveredPeer]:
        """Broadcasts DISCOVERY_PING and collects responses from standby peers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)

        ping = {
            "type": "DISCOVERY_PING",
            "machine_id": self.machine_id,
            "sender_ip": get_local_ip(),
        }
        data = json.dumps(ping).encode("utf-8")

        peers: Dict[str, DiscoveredPeer] = {}
        loop = asyncio.get_running_loop()

        for dest in self._get_destinations():
            try:
                sock.sendto(data, dest)
            except Exception as e:
                logger.debug("Discovery send error to %s: %s", dest, e)

        start_time = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start_time < timeout:
            try:
                resp_data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535),
                    timeout=max(0.1, timeout - (loop.time() - start_time)),
                )
                packet = json.loads(resp_data.decode("utf-8"))
                if packet.get("type") == "DISCOVERY_PONG":
                    p_id = packet.get("machine_id", addr[0])
                    reachable_ip = addr[0] if addr and addr[0] not in ("127.0.0.1", "localhost") else packet.get("ip", addr[0])
                    peers[p_id] = DiscoveredPeer(
                        machine_id=packet.get("machine_id", p_id),
                        machine_alias=packet.get("machine_alias", p_id),
                        ip=reachable_ip,
                        port=packet.get("port", self.port),
                        os_name=packet.get("os_name", "unknown"),
                        status=packet.get("status", "standby"),
                        capabilities=packet.get("capabilities", []),
                        extra=packet,
                    )
            except asyncio.TimeoutError:
                break
            except Exception:
                pass

        sock.close()
        return list(peers.values())

    async def wake_peer(
        self,
        session_id: str,
        relay_url: str,
        target_machine: Optional[str] = None,
        task_capsule_dict: Optional[Dict[str, Any]] = None,
        capsule_id: Optional[str] = None,
        timeout: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """Broadcasts WAKE_ACTIVATE packet to wake up standby machine(s)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)

        # Extract capsule_id if not explicitly provided
        resolved_cid = capsule_id
        if not resolved_cid and task_capsule_dict:
            resolved_cid = task_capsule_dict.get("capsule_id")

        # Datagram payload safety:
        # Standard UDP MTU on Ethernet is 1500 bytes (with IP/UDP headers, ~1472 payload).
        # Windows broadcast can reject packets exceeding interface limits with WinError 10040.
        # Only attach inline capsule dict if it's small (< 1024 bytes); otherwise send capsule_id
        # and remote peer will fetch it reliably via Relay REST / WebSocket.
        safe_capsule = None
        if task_capsule_dict:
            try:
                cap_json = json.dumps(task_capsule_dict)
                if len(cap_json.encode("utf-8")) <= 1024:
                    safe_capsule = task_capsule_dict
            except Exception:
                safe_capsule = None

        packet = {
            "type": "WAKE_ACTIVATE",
            "machine_id": self.machine_id,
            "session_id": session_id,
            "relay_url": relay_url,
            "target_machine": target_machine or "*",
            "capsule_id": resolved_cid,
            "capsule": safe_capsule,
        }
        data = json.dumps(packet).encode("utf-8")

        responses: List[Dict[str, Any]] = []
        loop = asyncio.get_running_loop()

        for dest in self._get_destinations(target_machine):
            try:
                sock.sendto(data, dest)
            except Exception as e:
                logger.debug("Wake broadcast error to %s: %s", dest, e)

        start_time = loop.time()
        while loop.time() - start_time < timeout:
            try:
                resp_data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535),
                    timeout=max(0.1, timeout - (loop.time() - start_time)),
                )
                ack = json.loads(resp_data.decode("utf-8"))
                if ack.get("type") == "WAKE_ACK":
                    responses.append(ack)
            except asyncio.TimeoutError:
                break
            except Exception:
                pass

        sock.close()
        return responses
