"""
Realistic Simulation Scenario 3:
Zero-Friction Cross-Machine Active Session & Cloud Capsule Sync
==============================================================
Simulates two distinct physical computers:
1. Machine B (Desktop / GPU Rig) sits in lightweight Standby Mode.
2. Machine A (Laptop) is where the user starts work on ticket 'API-CACHE-99'.
3. Machine A saves progress, pushes capsule to cloud/relay repository.
4. User initiates active cross-session from Machine A:
   - Zero config: LAN UDP discovery automatically finds Machine B.
   - Machine A wakes Machine B over the network.
   - Machine B unpacks the capsule and initializes workspace state.
   - Both machines link into real-time collaborative execution.
"""

import asyncio
import socket
import tempfile
import time
from pathlib import Path
import shutil

from agent_comms.capsule.cloud.relay import RelayCloudProvider
from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.models.capsule import EpistemicLearning, LearningCategory
from agent_comms.session.discovery import UDPDiscoveryBroadcaster, get_local_ip
from agent_comms.session.manager import CrossSessionManager
from agent_comms.session.standby import StandbyNode


def simulate_cross_session_and_cloud_sync():
    print("\n" + "=" * 70)
    print("SCENARIO 3: ZERO-FRICTION ACTIVE CROSS-SESSION & CLOUD CAPSULE SYNC")
    print("=" * 70)

    test_dir = Path("./tmp_scenario_cross_session").resolve()
    machine_a_ws = test_dir / "machine_a_laptop"
    machine_b_ws = test_dir / "machine_b_desktop"

    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)

    machine_a_ws.mkdir(parents=True, exist_ok=True)
    machine_b_ws.mkdir(parents=True, exist_ok=True)

    # 1. Machine A prepares local files
    (machine_a_ws / "cache_service.py").write_text(
        "# Redis caching service\ndef get_cache():\n    return {'status': 'active'}\n",
        encoding="utf-8",
    )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        udp_port = s.getsockname()[1]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        relay_port = s.getsockname()[1]

    async def run_scenario():
        print("[Machine B: Desktop] Starting in background Standby Mode...")
        standby_node = StandbyNode(
            machine_alias="gpu-desktop-rig",
            discovery_port=udp_port,
            workspace_path=machine_b_ws,
            auto_unpack_capsules=True,
        )
        await standby_node.start()
        await asyncio.sleep(0.1)

        print("[Machine A: Laptop] Developer packages handoff capsule for task 'API-CACHE-99'...")
        packager = CapsulePackager(workspace_path=machine_a_ws)
        capsule = packager.package(
            task_id="API-CACHE-99",
            title="Redis Tier-2 Caching Layer",
            executive_summary="Implemented memory cache; GPU load-testing required on desktop rig.",
            goal="Deploy and benchmark multi-tier caching across nodes",
            next_action="Run high-concurrency benchmark on GPU node",
            epistemic_learnings=[
                EpistemicLearning(
                    category=LearningCategory.ENVIRONMENT,
                    summary="Desktop GPU required for CUDA tensor caching benchmark",
                )
            ],
            agent_name="LaptopAgent",
        )

        print(f"[Machine A: Laptop] Generated Context Capsule: {capsule.capsule_id}")

        print("[Machine A: Laptop] Initiating active cross-session with single command...")
        print("[Machine A: Laptop] Zero configuration needed: discovering and activating peers...")
        manager = CrossSessionManager(
            machine_alias="macbook-laptop",
            workspace_path=machine_a_ws,
            discovery_port=udp_port,
        )

        session = await manager.start_session(
            session_id="cache-benchmark-live",
            target_machine="gpu-desktop-rig",
            capsule_or_id=capsule,
            relay_port=relay_port,
            timeout=5.0,
        )

        # Verify Machine B has awakened and received the capsule
        print("[Machine B: Desktop] Verifying automatic code and context restoration...")
        transferred_file = machine_b_ws / "cache_service.py"
        assert transferred_file.exists(), "File should be automatically restored on Machine B!"
        print("[Machine B: Desktop] Code successfully received and restored on Machine B!")

        # Verify cognitive sync
        print("[Machine A: Laptop] Asserting benchmark config to shared cognitive blackboard...")
        await session.broadcast_belief("benchmark_workers", 64, rationale="Max GPU parallelism")
        await asyncio.sleep(0.3)

        b_workers = standby_node.active_node.get_belief("benchmark_workers")
        assert b_workers == 64, "Belief should be instantly synchronized to Machine B!"
        print(f"[Machine B: Desktop] Read synchronized belief 'benchmark_workers': {b_workers}")

        print("[+] SUCCESS: Active cross-session started from one machine with zero user pain!")
        print("=" * 70 + "\n")

        await session.close()
        await standby_node.stop()

    try:
        asyncio.run(run_scenario())
    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    simulate_cross_session_and_cloud_sync()
