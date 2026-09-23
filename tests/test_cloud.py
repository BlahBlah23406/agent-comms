"""
Unit Tests for Cloud Capsule Storage
====================================
Tests cloud providers: Relay REST provider, S3 provider, GitHub provider,
and CapsuleStore cloud push/pull integrations.
"""

import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import uvicorn

from agent_comms.capsule.cloud.base import CloudCapsuleRecord
from agent_comms.capsule.cloud.factory import get_cloud_provider
from agent_comms.capsule.cloud.github import GitHubCloudProvider
from agent_comms.capsule.cloud.relay import RelayCloudProvider
from agent_comms.capsule.cloud.s3 import S3CloudProvider
from agent_comms.capsule.store import CapsuleStore
from agent_comms.models.capsule import (
    AgentMetadata,
    ContextCapsule,
    EpistemicLearning,
    LearningCategory,
    TaskGraph,
    TaskStep,
    WorkspacePatch,
)
from agent_comms.relay.server import create_app


def create_sample_capsule(task_id: str = "CLOUD-TEST-01") -> ContextCapsule:
    return ContextCapsule(
        task_id=task_id,
        title="Cloud Storage Unit Test",
        generator=AgentMetadata(
            agent_name="TestAgent",
            machine_id="test-machine",
            os_name="Linux",
        ),
        executive_summary="Testing cloud storage persistence and retrieval.",
        task_graph=TaskGraph(
            goal="Verify zero-friction cloud transfer",
            steps=[TaskStep(description="Push to cloud", status="completed")],
            next_action="Pull from second machine",
        ),
        epistemic_learnings=[
            EpistemicLearning(
                category=LearningCategory.FINDING,
                summary="Cloud storage works out of the box",
            )
        ],
        workspace=WorkspacePatch(
            untracked_files={"notes.txt": "Cloud sync notes"},
        ),
    )


class TestCloudStorage(unittest.TestCase):

    def setUp(self):
        self.temp_store_dir = Path(tempfile.mkdtemp(prefix="agent_comms_test_capsules_")).resolve()
        self.store = CapsuleStore(base_dir=self.temp_store_dir)
        self.capsule = create_sample_capsule()

    def tearDown(self):
        import shutil
        if self.temp_store_dir.exists():
            shutil.rmtree(self.temp_store_dir, ignore_errors=True)

    def test_relay_cloud_provider_upload_download(self):
        """Tests uploading to and downloading from Relay Cloud Provider."""
        import threading
        import time

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        app = create_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)

        t = threading.Thread(target=server.run, daemon=True)
        t.start()

        for _ in range(30):
            if server.started:
                break
            time.sleep(0.1)

        try:
            relay_url = f"http://127.0.0.1:{port}"
            provider = RelayCloudProvider(relay_url=relay_url)

            # 1. Upload
            loc = provider.upload(self.capsule)
            self.assertTrue(loc.startswith("relay://"))

            # 2. Download
            downloaded = provider.download(self.capsule.capsule_id)
            self.assertEqual(downloaded.capsule_id, self.capsule.capsule_id)
            self.assertEqual(downloaded.task_id, self.capsule.task_id)
            self.assertEqual(downloaded.workspace.untracked_files.get("notes.txt"), "Cloud sync notes")

            # 3. List
            records = provider.list_capsules()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].capsule_id, self.capsule.capsule_id)
        finally:
            server.should_exit = True
            t.join(timeout=2.0)

    @patch("agent_comms.capsule.cloud.s3.S3CloudProvider._get_client")
    def test_s3_cloud_provider(self, mock_get_client):
        """Tests S3 provider upload, download, and list with mocked boto3 client."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        provider = S3CloudProvider(bucket="my-test-bucket")

        # 1. Upload
        loc = provider.upload(self.capsule)
        self.assertEqual(loc, f"s3://my-test-bucket/capsules/{self.capsule.task_id}_{self.capsule.capsule_id}.json")
        self.assertTrue(mock_client.put_object.called)

        # 2. Download
        mock_body = MagicMock()
        mock_body.read.return_value = self.capsule.model_dump_json().encode("utf-8")
        mock_client.get_object.return_value = {"Body": mock_body}

        downloaded = provider.download(f"s3://my-test-bucket/capsules/{self.capsule.task_id}_{self.capsule.capsule_id}.json")
        self.assertEqual(downloaded.capsule_id, self.capsule.capsule_id)

    @patch("urllib.request.urlopen")
    def test_github_cloud_provider(self, mock_urlopen):
        """Tests GitHub Gist provider upload and download with mocked HTTP responses."""
        provider = GitHubCloudProvider(token="mock-gh-token")

        # Mock POST gist response
        mock_post_cm = MagicMock()
        mock_post_cm.__enter__.return_value.read.return_value = json.dumps({
            "id": "gist-mock-12345",
            "html_url": "https://gist.github.com/gist-mock-12345",
        }).encode("utf-8")

        # Mock GET gist response
        mock_get_cm = MagicMock()
        mock_get_cm.__enter__.return_value.read.return_value = json.dumps({
            "id": "gist-mock-12345",
            "description": f"[agent-comms] Context Capsule for {self.capsule.task_id}",
            "created_at": "2026-09-20T21:00:00Z",
            "files": {
                f"{self.capsule.task_id}_{self.capsule.capsule_id}.json": {
                    "content": self.capsule.model_dump_json()
                }
            }
        }).encode("utf-8")

        mock_urlopen.side_effect = [mock_post_cm, mock_get_cm]

        # 1. Upload
        loc = provider.upload(self.capsule)
        self.assertEqual(loc, "github://gist/gist-mock-12345")

        # 2. Download
        downloaded = provider.download("github://gist/gist-mock-12345")
        self.assertEqual(downloaded.capsule_id, self.capsule.capsule_id)

    def test_capsule_store_cloud_integration(self):
        """Tests CapsuleStore push_to_cloud and pull_from_cloud methods."""
        # Save locally first
        self.store.save(self.capsule)

        # Mock provider
        mock_provider = MagicMock()
        mock_provider.name = "mock-cloud"
        mock_provider.upload.return_value = f"mock://capsules/{self.capsule.capsule_id}"
        mock_provider.download.return_value = self.capsule

        with patch("agent_comms.capsule.store.get_cloud_provider", return_value=mock_provider):
            # Push
            loc = self.store.push_to_cloud(self.capsule.capsule_id, provider_name="mock-cloud")
            self.assertEqual(loc, f"mock://capsules/{self.capsule.capsule_id}")
            self.assertTrue(mock_provider.upload.called)

            # Pull
            pulled = self.store.pull_from_cloud(self.capsule.capsule_id, provider_name="mock-cloud")
            self.assertEqual(pulled.capsule_id, self.capsule.capsule_id)
            self.assertTrue(mock_provider.download.called)


if __name__ == "__main__":
    unittest.main()
