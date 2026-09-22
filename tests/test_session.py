"""
Unit & Integration Tests for Cross-Session & Instant Discovery
==============================================================
Tests UDP LAN Discovery, StandbyNode auto-activation, and
CrossSessionManager active multi-machine synchronization.
"""

import asyncio
import socket
import unittest
from pathlib import Path
import shutil

from agent_comms.capsule.store import CapsuleStore
from agent_comms.mesh.node import DualBrainNode
from agent_comms.models.capsule import (
    AgentMetadata,
    ContextCapsule,
    TaskGraph,
    WorkspacePatch,
)
from agent_comms.session.discovery import (
    UDPDiscoveryBroadcaster,
    UDPDiscoveryListener,
    get_local_ip,
)
from agent_comms.session.manager import CrossSessionManager
from agent_comms.session.standby import StandbyNode


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def get_free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestCrossSession(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.temp_dir = Path("./tmp_test_session").resolve()
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def asyncTearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_udp_discovery_ping_pong(self):
        """Tests that UDP broadcaster discovers a listening standby node."""
        udp_port = get_free_udp_port()

        listener = UDPDiscoveryListener(
            machine_alias="mock-standby-pc",
            port=udp_port,
            capabilities=["agent_comms", "gpu_acceleration"],
        )
        listener.start()
        await asyncio.sleep(0.1)

        try:
            broadcaster = UDPDiscoveryBroadcaster(port=udp_port)
            peers = await broadcaster.discover_peers(timeout=1.0)

            # We should discover mock-standby-pc
            matching = [p for p in peers if p.machine_alias == "mock-standby-pc"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].status, "standby")
            self.assertIn("gpu_acceleration", matching[0].capabilities)
        finally:
            listener.stop()

    async def test_udp_wake_activate(self):
        """Tests that WAKE_ACTIVATE packet wakes the standby node and calls its callback."""
        udp_port = get_free_udp_port()
        wake_event = asyncio.Event()
        received_packet = {}

        async def on_wake(packet, addr):
            nonlocal received_packet
            received_packet = packet
            wake_event.set()

        listener = UDPDiscoveryListener(
            machine_alias="target-worker",
            port=udp_port,
            on_wake=on_wake,
        )
        listener.start()
        await asyncio.sleep(0.1)

        try:
            broadcaster = UDPDiscoveryBroadcaster(port=udp_port)
            acks = await broadcaster.wake_peer(
                session_id="test-session-42",
                relay_url="ws://127.0.0.1:8765/ws",
                target_machine="target-worker",
                timeout=1.0,
            )

            self.assertTrue(len(acks) >= 1)
            self.assertEqual(acks[0]["status"], "activating")

            # Verify wake callback triggered
            await asyncio.wait_for(wake_event.wait(), timeout=1.0)
            self.assertEqual(received_packet.get("session_id"), "test-session-42")
        finally:
            listener.stop()

    async def test_cross_session_e2e_activation(self):
        """
        Full End-to-End Simulation:
        Machine A (Initiator) starts cross session.
        Machine B (StandbyNode) is awakened, receives capsule, and joins mesh.
        Both synchronize mental model facts across the session.
        """
        udp_port = get_free_udp_port()
        relay_port = get_free_port()

        # Create sample capsule
        capsule = ContextCapsule(
            task_id="E2E-TASK-100",
            title="Distributed Cross-Session Test",
            generator=AgentMetadata(
                agent_name="InitiatorAgent",
                machine_id="machine-a",
                os_name="Windows",
            ),
            executive_summary="Testing hands-free session activation and capsule delivery.",
            task_graph=TaskGraph(goal="Auto-activate Machine B"),
            workspace=WorkspacePatch(untracked_files={"ready.txt": "Worker is active"}),
        )

        # 1. Start StandbyNode on "Machine B"
        standby_node = StandbyNode(
            machine_alias="machine-b",
            discovery_port=udp_port,
            workspace_path=self.temp_dir,
            auto_unpack_capsules=True,
        )
        await standby_node.start()
        await asyncio.sleep(0.1)

        # 2. Start CrossSessionManager on "Machine A"
        manager = CrossSessionManager(
            machine_alias="machine-a",
            workspace_path=self.temp_dir,
            discovery_port=udp_port,
        )

        session = None
        try:
            session = await manager.start_session(
                session_id="cross-session-100",
                target_machine="machine-b",
                capsule_or_id=capsule,
                relay_port=relay_port,
                timeout=4.0,
            )

            self.assertIsNotNone(session)
            self.assertEqual(session.session_id, "cross-session-100")

            # 3. Verify StandbyNode on Machine B received and restored the capsule
            restored_file = self.temp_dir / "ready.txt"
            self.assertTrue(restored_file.exists())
            self.assertEqual(restored_file.read_text(encoding="utf-8"), "Worker is active")

            # 4. Verify shared cognitive blackboard sync between Machine A and Machine B
            await session.broadcast_belief("cluster_state", "optimal", rationale="Both nodes live")
            await asyncio.sleep(0.3)

            self.assertIsNotNone(standby_node.active_node)
            b_belief = standby_node.active_node.get_belief("cluster_state")
            self.assertEqual(b_belief, "optimal")

        finally:
            if session:
                await session.close()
            await standby_node.stop()


if __name__ == "__main__":
    unittest.main()
