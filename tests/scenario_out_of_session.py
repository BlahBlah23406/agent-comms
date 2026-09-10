"""
Realistic Simulation Scenario: Out-of-Session Cross-Machine Handover
====================================================================
Simulates:
1. Machine A (Laptop): Agent A begins work on an issue in a git repository.
   - Edits existing code
   - Adds a new test file (untracked)
   - Discovers subtle bugs and logs epistemic learnings
   - Packages state into a ContextCapsule
2. Machine B (Desktop / Cloud VM):
   - An independent workspace at the base commit
   - Agent B ingests the capsule
   - Restores the diff and untracked files
   - Uses the briefing and next action to complete the verification
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.models.capsule import (
    EpistemicLearning,
    LearningCategory,
    StepStatus,
    TaskStep,
)


def run_cmd(args, cwd):
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, check=True, encoding="utf-8"
    )


def simulate_out_of_session_handover():
    print("\n" + "=" * 70)
    print("SCENARIO 1: OUT-OF-SESSION CROSS-MACHINE AGENT HANDOFF SIMULATION")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        laptop_dir = root / "machine_laptop"
        desktop_dir = root / "machine_desktop"
        shared_store_dir = root / "cloud_capsule_store"

        laptop_dir.mkdir()
        desktop_dir.mkdir()
        shared_store_dir.mkdir()

        # Step 1: Setup a simulated base repository on Machine A
        print("\n[Machine A: Laptop] Initializing Git project...")
        run_cmd(["git", "init"], cwd=laptop_dir)
        run_cmd(["git", "config", "user.name", "DeveloperAgent"], cwd=laptop_dir)
        run_cmd(["git", "config", "user.email", "agent@laptop.local"], cwd=laptop_dir)

        calc_file = laptop_dir / "calculator.py"
        calc_file.write_text(
            "def divide(a, b):\n    # Bug: no zero check\n    return a / b\n",
            encoding="utf-8",
        )
        run_cmd(["git", "add", "calculator.py"], cwd=laptop_dir)
        run_cmd(["git", "commit", "-m", "Initial commit on main"], cwd=laptop_dir)

        # Clone base state into Machine B
        print("[Machine B: Desktop] Simulating checkout of the same base commit...")
        shutil.copytree(laptop_dir / ".git", desktop_dir / ".git")
        run_cmd(["git", "reset", "--hard", "HEAD"], cwd=desktop_dir)

        # Step 2: Agent A works on Machine A
        print("[Machine A: Laptop] Agent A modifies calculator.py and creates test...")
        calc_file.write_text(
            "def divide(a, b):\n    if b == 0:\n        raise ValueError('Cannot divide by zero')\n    return a / b\n",
            encoding="utf-8",
        )

        test_dir = laptop_dir / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_calc.py"
        test_file.write_text(
            "import unittest\n"
            "from calculator import divide\n\n"
            "class TestCalculator(unittest.TestCase):\n"
            "    def test_div(self):\n"
            "        self.assertEqual(divide(10, 2), 5)\n"
            "        with self.assertRaises(ValueError):\n"
            "            divide(10, 0)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )

        # Agent A records epistemic context
        learnings = [
            EpistemicLearning(
                category=LearningCategory.FINDING,
                summary="Zero division should raise standard ValueError with exact message",
                evidence="calculator.py:line 2",
            ),
            EpistemicLearning(
                category=LearningCategory.REJECTED_HYPOTHESIS,
                summary="Returning float('inf') breaks upstream JSON serializers",
                details="Tried math.inf, caused serialization failure in API tests",
            ),
            EpistemicLearning(
                category=LearningCategory.GOTCHA,
                summary="Test suite uses standard library unittest for zero-dependency test runner",
            ),
        ]

        steps = [
            TaskStep(description="Implement zero division guard", status=StepStatus.COMPLETED),
            TaskStep(description="Add unit tests in tests/test_calc.py", status=StepStatus.COMPLETED),
            TaskStep(description="Run test suite on desktop environment", status=StepStatus.PENDING),
        ]

        print("[Machine A: Laptop] Agent A packages Context Capsule before logging off...")
        store_a = CapsuleStore(base_dir=shared_store_dir)
        packager_a = CapsulePackager(workspace_path=laptop_dir, store=store_a)

        capsule = packager_a.package(
            task_id="CALC-BUG-404",
            title="Fix Zero Division in Calculator",
            goal="Ensure divide function handles zero divisor gracefully with ValueError",
            executive_summary="Implemented ValueError guard and added test_calc.py. Needs desktop test validation.",
            steps=steps,
            next_action="Run python -m unittest tests/test_calc.py and verify zero division check passes.",
            epistemic_learnings=learnings,
            agent_name="Agent_Laptop",
        )

        capsule_file = store_a.save(capsule)
        print(f"[Machine A: Laptop] Capsule saved to store: {capsule.capsule_id} ({capsule_file.name})")

        # Step 3: Agent B resumes on Machine B (Desktop)
        print("\n[Machine B: Desktop] Agent B wakes up, locates capsule, and inspects state...")
        store_b = CapsuleStore(base_dir=shared_store_dir)
        retrieved_capsule = store_b.load_by_id("CALC-BUG-404")
        assert retrieved_capsule is not None
        assert retrieved_capsule.capsule_id == capsule.capsule_id

        print(f"[Machine B: Desktop] Ingesting capsule from Agent '{retrieved_capsule.generator.agent_name}'...")
        unpacker_b = CapsuleUnpacker(workspace_path=desktop_dir)
        restore_result = unpacker_b.apply(retrieved_capsule, apply_workspace=True)

        print(f"[Machine B: Desktop] Patch Applied: {restore_result['git_patch_message']}")
        print(f"[Machine B: Desktop] Restored Files: {restore_result['untracked_files_restored']}")

        # Verify filesystem state on Desktop
        desktop_calc = desktop_dir / "calculator.py"
        desktop_test = desktop_dir / "tests" / "test_calc.py"

        assert desktop_calc.exists(), "calculator.py missing on Machine B"
        assert desktop_test.exists(), "tests/test_calc.py missing on Machine B"
        assert "Cannot divide by zero" in desktop_calc.read_text(encoding="utf-8")

        print("\n[Machine B: Desktop] Verification: Running unittest suite on Machine B...")
        test_run = subprocess.run(
            [sys.executable, "-m", "unittest", "tests/test_calc.py"],
            cwd=str(desktop_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        print(test_run.stderr or test_run.stdout)
        assert test_run.returncode == 0, f"Tests failed on Machine B: {test_run.stderr}"

        print("[+] SUCCESS: Machine B completed the task with zero context loss and zero token waste!")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    simulate_out_of_session_handover()
