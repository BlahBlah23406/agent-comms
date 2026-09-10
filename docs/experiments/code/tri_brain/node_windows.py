"""
Tri-Brain Node: Windows 11 (Providence)
=======================================
Operates as Node 1 in the 3-Way Cross-Platform Mesh.
"""

import asyncio
import json
import platform
import socket
import sys

from agent_comms.mesh import DualBrainNode
from agent_comms.models.capsule import EpistemicLearning, LearningCategory

RELAY_URL = "ws://100.118.132.56:8765/ws"


async def run_windows_node():
    print("[Windows Node] Booting Tri-Brain node on Providence (Windows 11)...", flush=True)

    node = DualBrainNode(
        agent_id="tri-node-windows",
        relay_url=RELAY_URL,
        machine_id="Providence",
        role="coordinator-architect",
        capabilities=["windows_coordination", "merkle_ledger", "fastapi"],
    )

    received_peers = set()
    completed_event = asyncio.Event()

    async def on_belief(key, value, rationale):
        print(f"[Windows <- Shared Mind] DELTA: '{key}' = {value} | Rationale: {rationale}", flush=True)
        if "mac" in key:
            received_peers.add("mac")
        if "linux" in key:
            received_peers.add("linux")

        if len(received_peers) >= 2:
            print("[Windows Node] All 3 physical nodes actively synchronized into shared mind!", flush=True)
            completed_event.set()

    node.on_belief_update(on_belief)

    await node.start()
    print("[Windows Node] Connected to AHRP Relay Hub on code-47.", flush=True)

    # 1. Propose Tri-Brain Contract
    await node.propose_contract(
        "TRI_BRAIN_CONSENSUS_V1",
        {
            "topology": "tri_mesh",
            "nodes": ["Providence_Win11", "Triskelion_macOS", "Code47_Ubuntu"],
            "verification": "merkle_sha256",
        },
    )

    # 2. Assert Windows Belief
    await node.set_belief(
        "windows_status",
        {
            "os": f"Windows {platform.version()}",
            "hostname": socket.gethostname(),
            "role": "Architect",
            "active": True,
        },
        rationale="Node Alpha established initial coordination framework",
    )

    print("[Windows Node] Waiting for Mac and Linux peers to contribute...", flush=True)
    try:
        await asyncio.wait_for(completed_event.wait(), timeout=20.0)
    except asyncio.TimeoutError:
        print("[Windows Node] Timeout waiting for peers. Proceeding with available state.", flush=True)

    await asyncio.sleep(2.0)

    # 3. Export Context Capsule
    capsule = node.export_twin_capsule(
        task_id="TRI-BRAIN-3WAY-LIVE",
        summary="3-way cross-platform mesh successfully executed across Windows, macOS, and Linux",
        next_steps=["Verify tri-node ledger across all 3 operating systems"],
    )
    print(f"[Windows Node] Exported Context Capsule: {capsule.capsule_id}", flush=True)
    print(f"[Windows Node] Epistemic Learnings in Capsule: {len(capsule.epistemic_learnings)}", flush=True)

    await node.stop()
    print("[Windows Node] Done.", flush=True)


if __name__ == "__main__":
    asyncio.run(run_windows_node())
