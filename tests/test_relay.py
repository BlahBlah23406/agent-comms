"""
Unit and integration tests for Live Relay Server and Client
"""

import asyncio
import socket
import unittest
import uvicorn
from agent_comms.relay.client import AgentRelayClient
from agent_comms.relay.server import create_app


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestRelay(unittest.IsolatedAsyncioTestCase):
    async def test_relay_pubsub_and_rpc(self):
        port = get_free_port()
        app = create_app()

        # Start server in background task
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        # Wait for server to boot
        for _ in range(25):
            if server.started:
                break
            await asyncio.sleep(0.1)

        relay_url = f"ws://127.0.0.1:{port}/ws"

        # Agent A (Caller)
        client_a = AgentRelayClient(agent_id="agent-a", relay_url=relay_url, capabilities=["planner"])
        # Agent B (Worker)
        client_b = AgentRelayClient(agent_id="agent-b", relay_url=relay_url, capabilities=["executor"])

        # Register RPC handler on Agent B
        async def add_numbers(params):
            return {"sum": params["a"] + params["b"]}

        client_b.register_rpc_handler("add", add_numbers)

        # Setup Topic Callback on Agent A
        received_events = []
        async def on_event(frame):
            received_events.append(frame.payload)

        await client_a.connect()
        await client_b.connect()

        # Agent A subscribes to topic
        await client_a.subscribe("build-events", on_event)
        await asyncio.sleep(0.1)

        # Agent B publishes to topic
        await client_b.publish("build-events", {"status": "started", "job": 42})
        await asyncio.sleep(0.2)

        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0]["status"], "started")

        # Agent A calls RPC on Agent B
        rpc_result = await client_a.rpc("agent-b", "add", {"a": 15, "b": 27})
        self.assertEqual(rpc_result, {"sum": 42})

        # Peer discovery
        peers = await client_a.list_peers()
        peer_ids = [p.agent_id for p in peers]
        self.assertIn("agent-a", peer_ids)
        self.assertIn("agent-b", peer_ids)

        # Cleanup
        await client_a.disconnect()
        await client_b.disconnect()
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    unittest.main()
