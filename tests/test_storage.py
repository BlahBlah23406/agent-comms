"""
Unit & Integration Tests for Unified Capsule Storage Server
===========================================================
Tests CapsuleStorageServer, REST API endpoints, StorageServerProvider,
and CapsuleStore fleet-wide synchronization.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from agent_comms.capsule.server import CapsuleStorageServer, create_storage_app
from agent_comms.capsule.store import CapsuleStore
from agent_comms.models.capsule import (
    AgentMetadata,
    ContextCapsule,
    EpistemicLearning,
    LearningCategory,
    TaskGraph,
    TaskStep,
    StepStatus,
    WorkspacePatch,
)


def create_sample_capsule(task_id: str = "TASK-STORAGE-1", title: str = "Test Storage Capsule") -> ContextCapsule:
    return ContextCapsule(
        capsule_id=f"cap-{task_id.lower()}",
        task_id=task_id,
        title=title,
        executive_summary="Verified unified storage architecture.",
        task_graph=TaskGraph(
            goal="Test persistent disk storage server",
            next_action="Verify retrieval and briefings",
            steps=[TaskStep(id="s1", description="Store capsule", status=StepStatus.COMPLETED)],
        ),
        epistemic_learnings=[
            EpistemicLearning(
                category=LearningCategory.FINDING,
                summary="Storage server correctly persists JSON and MD",
            )
        ],
        workspace=WorkspacePatch(
            git_diff="diff --git a/test.txt b/test.txt\n+hello world",
            modified_files=["test.txt"],
        ),
        generator=AgentMetadata(
            agent_name="StorageTester",
            machine_id="test-node",
            os_name="Linux",
        ),
    )


class TestCapsuleStorageServer(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="agent_comms_test_storage_")).resolve()
        self.server = CapsuleStorageServer(storage_dir=self.temp_dir)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_store_and_retrieve_capsule(self):
        cap = create_sample_capsule()
        rec = self.server.store_capsule(cap.model_dump())

        self.assertEqual(rec["capsule_id"], cap.capsule_id)
        self.assertEqual(rec["task_id"], cap.task_id)

        # Retrieve JSON
        loaded = self.server.get_capsule(cap.capsule_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["task_id"], cap.task_id)

        # Retrieve Markdown briefing
        briefing = self.server.get_briefing(cap.capsule_id)
        self.assertIsNotNone(briefing)
        self.assertIn("Verified unified storage architecture", briefing)

    def test_list_and_search_capsules(self):
        cap1 = create_sample_capsule("TASK-ALPHA", "Alpha Feature")
        cap2 = create_sample_capsule("TASK-BETA", "Beta Refactoring")

        self.server.store_capsule(cap1.model_dump())
        self.server.store_capsule(cap2.model_dump())

        all_caps = self.server.list_capsules()
        self.assertEqual(len(all_caps), 2)

        # Filter by query
        filtered = self.server.list_capsules(query="refactoring")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["task_id"], "TASK-BETA")

    def test_delete_capsule(self):
        cap = create_sample_capsule("TASK-DEL", "To Delete")
        self.server.store_capsule(cap.model_dump())

        self.assertIsNotNone(self.server.get_capsule(cap.capsule_id))
        deleted = self.server.delete_capsule(cap.capsule_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.server.get_capsule(cap.capsule_id))

    def test_reload_index(self):
        cap = create_sample_capsule("TASK-RELOAD", "Reload Test")
        self.server.store_capsule(cap.model_dump())

        # Create a new server instance pointing to same directory
        new_server = CapsuleStorageServer(storage_dir=self.temp_dir)
        self.assertEqual(len(new_server._index), 1)
        self.assertIsNotNone(new_server.get_capsule(cap.capsule_id))


class TestStorageRESTAPI(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="agent_comms_test_api_")).resolve()
        self.server = CapsuleStorageServer(storage_dir=self.temp_dir)
        self.app = create_storage_app(storage_server=self.server)
        self.client = TestClient(self.app)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_api_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")

    def test_api_upload_and_download(self):
        cap = create_sample_capsule("TASK-API-1", "REST API Capsule")
        upload_resp = self.client.post("/capsules", json=cap.model_dump())
        self.assertEqual(upload_resp.status_code, 200)
        up_data = upload_resp.json()
        self.assertEqual(up_data["status"], "stored")

        # Download JSON
        get_resp = self.client.get(f"/capsules/{cap.capsule_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["capsule_id"], cap.capsule_id)

        # Download Briefing
        briefing_resp = self.client.get(f"/capsules/{cap.capsule_id}/briefing")
        self.assertEqual(briefing_resp.status_code, 200)
        self.assertIn("Context Capsule Handover", briefing_resp.text)

        # List
        list_resp = self.client.get("/capsules")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()), 1)

        # Delete
        del_resp = self.client.delete(f"/capsules/{cap.capsule_id}")
        self.assertEqual(del_resp.status_code, 200)

        # 404 after delete
        self.assertEqual(self.client.get(f"/capsules/{cap.capsule_id}").status_code, 404)
