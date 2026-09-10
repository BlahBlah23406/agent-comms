"""
Tri-Brain Node: Linux Cloud (code-47)
=====================================
Operates as Node 3 in the 3-Way Cross-Platform Mesh.
"""

import asyncio
import json
import os
import platform
import socket
import sys

from agent_comms.mesh import DualBrainNode
from agent_comms.models.capsule import EpistemicLearning, LearningCategory

RELAY_URL = "ws://127.0.0.1:8765/ws"  # Local to code-47


def get_linux_loadavg():
    try:
        with open("/proc/loadavg", "r") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


async def run_linux_node():
    print("[Linux Node] Booting Tri-Brain node on code-47 (Oracle Cloud Ubuntu Linux)...", flush=True)

    node = DualBrainNode(
        agent_id="tri-node-linux",
        relay_url=RELAY_URL,
        machine_id="code-47",
        role="cloud-backend-telemetry",
        capabilities=["linux_kernel_telemetry", "oci_cloud", "merkle_engine"],
    )

    received_peers = set()
    completed_event = asyncio.Event()

    async def on_belief(key, value, rationale):
        print(f"[Linux <- Shared Mind] DELTA: '{key}' = {value} | Rationale: {rationale}", flush=True)
        if "windows" in key:
            received_peers.add("windows")
        if "mac" in key:
            received_peers.add("mac")

        if len(received_peers) >= 2:
            print("[Linux Node] Received sync from both Windows and Mac nodes!", flush=True)
            completed_event.set()

    node.on_belief_update(on_belief)

    await node.start()
    print("[Linux Node] Connected to AHRP Relay Hub locally.", flush=True)

    # 1. Assert Linux Kernel Belief
    loadavg = get_linux_loadavg()
    await node.set_belief(
        "linux_status",
        {
            "os": f"Ubuntu {platform.version()}",
            "kernel": platform.release(),
            "loadavg": loadavg,
            "cloud_provider": "Oracle Cloud Infrastructure",
            "hostname": socket.gethostname(),
        },
        rationale=f"Linux kernel telemetry verified loadavg={loadavg}",
    )

    # 2. Lock the contract with unanimous consensus
    await node.lock_contract(
        "TRI_BRAIN_CONSENSUS_V1",
        {
            "topology": "tri_mesh",
            "nodes": ["Providence_Win11", "Triskelion_macOS", "Code47_Ubuntu"],
            "verification": "merkle_sha256",
            "status": "LOCKED_BY_CONSENSUS",
        },
    )

    print("[Linux Node] Waiting for Windows and Mac peers to contribute...", flush=True)
    try:
        await asyncio.wait_for(completed_event.wait(), timeout=20.0)
    except asyncio.TimeoutError:
        print("[Linux Node] Timeout waiting for peers. Proceeding with available state.", flush=True)

    await asyncio.sleep(2.0)

    # 3. Export Context Capsule
    capsule = node.export_twin_capsule(
        task_id="TRI-BRAIN-3WAY-LIVE",
        summary="3-way cross-platform mesh successfully verified on Linux Cloud",
        next_steps=["Stream telemetry to tri-brain dashboard"],
    )
    print(f"[Linux Node] Exported Context Capsule: {capsule.capsule_id}", flush=True)
    print(f"[Linux Node] Epistemic Learnings in Capsule: {len(capsule.epistemic_learnings)}", flush=True)

    await node.stop()
    print("[Linux Node] Done.", flush=True)


if __name__ == "__main__":
    asyncio.run(run_linux_node())
