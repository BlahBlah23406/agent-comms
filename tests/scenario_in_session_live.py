"""
Realistic Simulation Scenario: In-Session Live Real-Time Agent Collaboration
===========================================================================
Simulates:
1. Relay Hub running on network (or local machine)
2. Agent_Orchestrator (e.g. Developer Laptop)
3. Agent_RemoteWorker (e.g. Remote Cloud Server with specialized tools)
Demonstrates:
- Peer discovery & capability advertising across machines
- Live Topic Pub/Sub event broadcasting
- Bidirectional Remote Procedure Calls (RPC)
- Graceful execution and state synchronization
"""

import asyncio
import socket
import uvicorn
from agent_comms.relay.client import AgentRelayClient
from agent_comms.relay.server import create_app


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def simulate_live_session():
    print("\n" + "=" * 70)
    print("SCENARIO 2: IN-SESSION LIVE CROSS-MACHINE AGENT COLLABORATION")
    print("=" * 70)

    port = get_free_port()
    app = create_app()

    print(f"\n[Hub] Starting Live AHRP Relay Server on 127.0.0.1:{port}...")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    for _ in range(25):
        if server.started:
            break
        await asyncio.sleep(0.1)

    relay_url = f"ws://127.0.0.1:{port}/ws"

    # Initialize Agent 1: Developer Agent on Laptop
    agent_laptop = AgentRelayClient(
        agent_id="agent_laptop_orchestrator",
        machine_id="macbook-laptop",
        framework="Antigravity",
        capabilities=["planner", "code_editor"],
        relay_url=relay_url,
    )

    # Initialize Agent 2: Remote Worker Agent on High-Performance Server
    agent_worker = AgentRelayClient(
        agent_id="agent_cloud_worker",
        machine_id="cloud-compute-node-01",
        framework="Claude-Code-Worker",
        capabilities=["gpu_acceleration", "docker_runner", "pytest_matrix"],
        relay_url=relay_url,
    )

    # Register RPC handlers on the Worker Agent
    async def handle_run_matrix(params):
        task_name = params.get("suite", "smoke")
        print(f"[Remote Worker] Executing RPC request '{task_name}' on Cloud GPU node...")
        # Broadcast intermediate progress
        await agent_worker.publish(
            "pipeline.progress",
            {"stage": "compilation", "progress": 50, "status": "OK"},
        )
        await asyncio.sleep(0.2)
        await agent_worker.publish(
            "pipeline.progress",
            {"stage": "gpu_benchmarking", "progress": 100, "status": "COMPLETED"},
        )
        return {
            "status": "success",
            "tests_run": 142,
            "failed": 0,
            "gpu_device": "NVIDIA A100-SXM4-80GB",
            "execution_time_sec": 1.48,
        }

    agent_worker.register_rpc_handler("run_test_matrix", handle_run_matrix)

    # Connect both agents
    print("[Agent Laptop] Connecting to relay hub...")
    await agent_laptop.connect()
    print("[Agent Cloud Worker] Connecting to relay hub...")
    await agent_worker.connect()

    # Laptop agent listens for live pipeline progress events
    captured_progress = []
    async def on_progress(frame):
        print(f"[Agent Laptop Monitor] Received Event on '{frame.topic}': {frame.payload}")
        captured_progress.append(frame.payload)

    await agent_laptop.subscribe("pipeline.progress", on_progress)
    await asyncio.sleep(0.1)

    # Step 1: Peer Discovery
    print("\n[Agent Laptop] Querying network for active peers and capabilities...")
    peers = await agent_laptop.list_peers()
    print(f"[Agent Laptop] Discovered {len(peers)} peers on network:")
    for p in peers:
        print(f"  - Agent: `{p.agent_id}` on `{p.machine_id}` | Capabilities: {p.capabilities}")

    worker_peer = next((p for p in peers if p.agent_id == "agent_cloud_worker"), None)
    assert worker_peer is not None, "Worker peer not discovered"
    assert "gpu_acceleration" in worker_peer.capabilities

    # Step 2: Agent Laptop issues remote execution RPC to Cloud Worker
    print("\n[Agent Laptop] Delegating heavy test matrix to Agent Cloud Worker via RPC...")
    result = await agent_laptop.rpc(
        target_id="agent_cloud_worker",
        method="run_test_matrix",
        params={"suite": "deep_learning_integration", "precision": "fp16"},
        timeout=10.0,
    )

    print("\n[Agent Laptop] Received Remote RPC Execution Result:")
    print(f"  - Tests Run: {result['tests_run']}")
    print(f"  - GPU Used: {result['gpu_device']}")
    print(f"  - Execution Time: {result['execution_time_sec']}s")

    assert result["status"] == "success"
    assert len(captured_progress) >= 2

    # Step 3: Cleanup
    print("\n[Teardown] Disconnecting agents and stopping relay server...")
    await agent_laptop.disconnect()
    await agent_worker.disconnect()
    server.should_exit = True
    await server_task

    print("[+] SUCCESS: Real-time distributed multi-machine agent collaboration verified!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(simulate_live_session())
