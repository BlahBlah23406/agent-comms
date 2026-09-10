"""
Unit and integration tests for Peer-to-Peer Dual-Brain Mesh and CognitiveBlackboard
"""

import asyncio
import socket
import unittest
import uvicorn

from agent_comms.relay.server import create_app
from agent_comms.mesh import DualBrainNode, CognitiveBlackboard


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestMesh(unittest.IsolatedAsyncioTestCase):
    async def test_dual_brain_cognitive_sync_and_twin_capsules(self):
        port = get_free_port()
        app = create_app()

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        for _ in range(25):
            if server.started:
                break
            await asyncio.sleep(0.1)

        relay_url = f"ws://127.0.0.1:{port}/ws"

        # Instantiate Node Alpha (Left Hemisphere) and Node Beta (Right Hemisphere)
        node_alpha = DualBrainNode(
            agent_id="node-alpha",
            relay_url=relay_url,
            machine_id="host-alpha",
            role="left-hemisphere",
        )
        node_beta = DualBrainNode(
            agent_id="node-beta",
            relay_url=relay_url,
            machine_id="host-beta",
            role="right-hemisphere",
        )

        await node_alpha.start()
        await node_beta.start()
        await asyncio.sleep(0.15)

        # 1. Test Cognitive Delta propagation from Alpha -> Beta
        beta_deltas = []

        async def on_beta_belief(key, val, rationale):
            beta_deltas.append((key, val, rationale))

        node_beta.on_belief_update(on_beta_belief)

        await node_alpha.set_belief("dataset_size", 10000, rationale="Batch stream configured")
        await asyncio.sleep(0.15)

        self.assertEqual(len(beta_deltas), 1)
        self.assertEqual(beta_deltas[0][0], "dataset_size")
        self.assertEqual(beta_deltas[0][1], 10000)
        self.assertEqual(beta_deltas[0][2], "Batch stream configured")
        self.assertEqual(node_beta.get_belief("dataset_size"), 10000)

        # 2. Test Cognitive Delta propagation from Beta -> Alpha
        alpha_deltas = []

        async def on_alpha_belief(key, val, rationale):
            alpha_deltas.append((key, val, rationale))

        node_alpha.on_belief_update(on_alpha_belief)

        await node_beta.set_belief("presort_vector", True, rationale="Hardware branch optimization")
        await asyncio.sleep(0.15)

        self.assertEqual(len(alpha_deltas), 1)
        self.assertEqual(alpha_deltas[0][0], "presort_vector")
        self.assertEqual(alpha_deltas[0][1], True)
        self.assertEqual(node_alpha.get_belief("presort_vector"), True)

        # 3. Test Symmetrical Contract Negotiation & Consensus
        contract_events = []

        async def on_contract(name, schema, event_type):
            contract_events.append((name, schema, event_type))

        node_beta.on_contract_event(on_contract)

        await node_alpha.propose_contract("test_pipeline", {"dim": "int"})
        await asyncio.sleep(0.15)

        self.assertEqual(len(contract_events), 1)
        self.assertEqual(contract_events[0][0], "test_pipeline")
        self.assertEqual(contract_events[0][2], "CONTRACT_PROPOSAL")

        await node_beta.lock_contract("test_pipeline", {"dim": "int", "status": "locked"})
        await asyncio.sleep(0.15)

        self.assertEqual(node_beta.blackboard.get_contract("test_pipeline")["status"], "locked")

        # 4. Test Twin Context Capsule Export
        capsule_alpha = node_alpha.export_twin_capsule(
            task_id="TEST-DUAL-01",
            summary="Node Alpha sync verification",
            next_steps=["Deploy distributed worker"],
        )
        capsule_beta = node_beta.export_twin_capsule(
            task_id="TEST-DUAL-01",
            summary="Node Beta sync verification",
            next_steps=["Verify Merkle root"],
        )

        self.assertEqual(capsule_alpha.task_id, "TEST-DUAL-01")
        self.assertEqual(capsule_beta.task_id, "TEST-DUAL-01")
        self.assertEqual(capsule_alpha.generator.agent_name, "node-alpha")
        self.assertEqual(capsule_beta.generator.agent_name, "node-beta")

        # Confirm shared beliefs are encapsulated into epistemic learnings
        alpha_learnings_summaries = [l.summary for l in capsule_alpha.epistemic_learnings]
        self.assertTrue(any("dataset_size" in s for s in alpha_learnings_summaries))
        self.assertTrue(any("presort_vector" in s for s in alpha_learnings_summaries))

        # Cleanup
        await node_alpha.stop()
        await node_beta.stop()
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    unittest.main()
