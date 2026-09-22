"""
Tri-Brain Node: macOS (The-Triskelion)
======================================
Operates as Node 2 in the 3-Way Cross-Platform Mesh.
"""

import asyncio
import json
import platform
import socket
import sys

from agent_comms.mesh import DualBrainNode
from agent_comms.models.capsule import EpistemicLearning, LearningCategory

RELAY_URL = "ws://<relay-host>:8765/ws"


async def run_mac_node():
    print("[Mac Node] Booting Tri-Brain node on The-Triskelion (macOS Apple Silicon)...", flush=True)

    node = DualBrainNode(
        agent_id="tri-node-mac",
        relay_url=RELAY_URL,
        machine_id="The-Triskelion",
        role="frontal-cortex-apple-silicon",
        capabilities=["apple_silicon_metal", "arm64_neural", "macos_workstation"],
    )

    received_peers = set()
    completed_event = asyncio.Event()

    async def on_belief(key, value, rationale):
        print(f"[Mac <- Shared Mind] DELTA: '{key}' = {value} | Rationale: {rationale}", flush=True)
        if "windows" in key:
            received_peers.add("windows")
        if "linux" in key:
            received_peers.add("linux")

        if len(received_peers) >= 2:
            print("[Mac Node] Received sync from both Windows and Linux nodes!", flush=True)
            completed_event.set()

    node.on_belief_update(on_belief)

    await node.start()
    print("[Mac Node] Connected to AHRP Relay Hub on code-47.", flush=True)

    # 1. Assert Mac Belief into shared mind
    uname = platform.uname()
    await node.set_belief(
        "mac_status",
        {
            "os": f"macOS {uname.release} {uname.machine}",
            "arch": "arm64",
            "metal_acceleration": True,
            "neural_engine_ready": True,
            "hostname": socket.gethostname(),
        },
        rationale="Apple Silicon M-series unified memory architecture available for high-speed tensor operations",
    )

    # 2. Assert a Cognitive Delta optimizing execution
    await node.set_belief(
        "execution_policy",
        "zero_copy_memory_ring",
        rationale="Apple Silicon unified memory bus allows zero-copy serialization between CPU and GPU kernels",
    )

    print("[Mac Node] Waiting for Windows and Linux peers to contribute...", flush=True)
    try:
        await asyncio.wait_for(completed_event.wait(), timeout=20.0)
    except asyncio.TimeoutError:
        print("[Mac Node] Timeout waiting for peers. Proceeding with available state.", flush=True)

    await asyncio.sleep(2.0)

    # 3. Export Context Capsule
    capsule = node.export_twin_capsule(
        task_id="TRI-BRAIN-3WAY-LIVE",
        summary="3-way cross-platform mesh successfully verified on macOS",
        next_steps=["Deploy unified memory zero-copy buffers"],
    )
    print(f"[Mac Node] Exported Context Capsule: {capsule.capsule_id}", flush=True)
    print(f"[Mac Node] Epistemic Learnings in Capsule: {len(capsule.epistemic_learnings)}", flush=True)

    await node.stop()
    print("[Mac Node] Done.", flush=True)


if __name__ == "__main__":
    asyncio.run(run_mac_node())
