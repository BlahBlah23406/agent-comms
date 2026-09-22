"""
Master Test & Scenario Runner
=============================
Runs all unit tests, integration tests, and realistic simulation scenarios
for the Agent Communication & Handover Suite using standard library unittest.
"""

import asyncio
import sys
import unittest
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_unit_tests():
    print("\n" + "=" * 70)
    print("RUNNING UNIT & INTEGRATION TEST SUITE (UNITTEST)")
    print("=" * 70)
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(PROJECT_ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def run_scenarios():
    print("\n" + "=" * 70)
    print("RUNNING REALISTIC SIMULATION SCENARIOS")
    print("=" * 70)

    # Scenario 1: Out-of-session
    from tests.scenario_out_of_session import simulate_out_of_session_handover
    start_time = time.time()
    simulate_out_of_session_handover()
    s1_time = time.time() - start_time

    # Scenario 2: In-session live
    from tests.scenario_in_session_live import simulate_live_session
    start_time = time.time()
    asyncio.run(simulate_live_session())
    s2_time = time.time() - start_time

    # Scenario 3: Cross-session activation and cloud sync
    from tests.scenario_cross_session_cloud import simulate_cross_session_and_cloud_sync
    start_time = time.time()
    simulate_cross_session_and_cloud_sync()
    s3_time = time.time() - start_time

    # Scenario 4: Preemptive Quota Detection & Auto-Evacuation Handoff
    from tests.scenario_quota_evacuation import simulate_quota_evacuation
    start_time = time.time()
    simulate_quota_evacuation()
    s4_time = time.time() - start_time

    return s1_time, s2_time, s3_time, s4_time


def main():
    print("\n" + "#" * 70)
    print("# AGENT-COMMS VERIFICATION & SIMULATION SUITE")
    print("#" * 70)

    unit_ok = run_unit_tests()
    if not unit_ok:
        print("[-] Unit tests failed!")
        sys.exit(1)

    s1_time, s2_time, s3_time, s4_time = run_scenarios()

    print("\n" + "=" * 70)
    print("ALL TESTS & REALISTIC SCENARIOS COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"[x] Unit Tests: PASSED")
    print(f"[x] Out-of-Session Cross-Machine Handoff: PASSED ({s1_time:.2f}s)")
    print(f"[x] In-Session Live Cross-Machine Collaboration: PASSED ({s2_time:.2f}s)")
    print(f"[x] Active Cross-Session & Instant Auto-Wake: PASSED ({s3_time:.2f}s)")
    print(f"[x] Preemptive Rate-Limit Quota Evacuation: PASSED ({s4_time:.2f}s)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
