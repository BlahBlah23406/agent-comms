"""
Unit tests for Context Capsule data models and packaging
"""

import unittest
from agent_comms.models.capsule import (
    ContextCapsule,
    AgentMetadata,
    TaskGraph,
    TaskStep,
    StepStatus,
    EpistemicLearning,
    LearningCategory,
    WorkspacePatch,
)


class TestCapsule(unittest.TestCase):
    def test_capsule_serialization(self):
        generator = AgentMetadata(
            agent_name="Antigravity",
            machine_id="node-alpha",
            os_name="Windows",
        )
        steps = [
            TaskStep(description="Setup auth scaffolding", status=StepStatus.COMPLETED),
            TaskStep(description="Integrate JWT verification", status=StepStatus.IN_PROGRESS),
            TaskStep(description="Write unit tests", status=StepStatus.PENDING),
        ]
        task_graph = TaskGraph(
            goal="Implement JWT Auth",
            steps=steps,
            next_action="Finish test_jwt_expiry in test_auth.py",
        )
        learnings = [
            EpistemicLearning(
                category=LearningCategory.FINDING,
                summary="Python 3.12 requires argon2-cffi >= 23.1.0",
            ),
            EpistemicLearning(
                category=LearningCategory.REJECTED_HYPOTHESIS,
                summary="Tried PyCrypto, incompatible with OpenSSL 3; using cryptography instead",
            ),
        ]
        workspace = WorkspacePatch(
            is_git_repo=True,
            branch_name="feat/jwt-auth",
            base_commit="e4b81c2",
            modified_files=["auth.py"],
            untracked_files={"tests/test_auth.py": "def test_token(): assert True\n"},
        )

        capsule = ContextCapsule(
            task_id="AUTH-101",
            title="Migrate Auth to JWT",
            generator=generator,
            executive_summary="Implemented token generation. Verification tests in progress.",
            task_graph=task_graph,
            epistemic_learnings=learnings,
            workspace=workspace,
        )

        # Test JSON round-trip
        dumped = capsule.model_dump_json()
        reloaded = ContextCapsule.model_validate_json(dumped)

        self.assertEqual(reloaded.task_id, "AUTH-101")
        self.assertEqual(reloaded.generator.agent_name, "Antigravity")
        self.assertEqual(len(reloaded.task_graph.steps), 3)
        self.assertEqual(len(reloaded.epistemic_learnings), 2)
        self.assertIn("tests/test_auth.py", reloaded.workspace.untracked_files)

        # Test Markdown briefing generation
        briefing = reloaded.to_briefing_markdown()
        self.assertIn("# Context Capsule Handover: Migrate Auth to JWT", briefing)
        self.assertIn("AUTH-101", briefing)
        self.assertIn("Python 3.12 requires argon2-cffi", briefing)
        self.assertIn("Finish test_jwt_expiry", briefing)


if __name__ == "__main__":
    unittest.main()
