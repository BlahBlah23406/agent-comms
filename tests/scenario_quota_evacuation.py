"""
Simulation Scenario 4:
Preemptive Rate-Limit Quota Detection & Auto-Evacuation Handoff
===============================================================
Simulates an active agent working on a critical refactoring task:
1. Agent A (using Anthropic Claude) performs heavy token-consuming work.
2. During the session, provider rate-limit response headers report requests/tokens
   rapidly approaching exhaustion (e.g. 1 request remaining before 429 lockout).
3. QuotaGuard detects the critical threshold and automatically triggers PREEMPTIVE EVACUATION.
4. An evacuation Context Capsule is packaged, capturing uncommitted files, diffs,
   and epistemic learnings about the quota reset window.
5. Agent B (running Gemini or OpenAI on another machine/account) immediately resumes
   the task with zero context loss and zero token waste.
"""

import tempfile
from pathlib import Path
import shutil

from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.quota.guard import QuotaGuard
from agent_comms.quota.models import QuotaBudget, QuotaWindow
from agent_comms.quota.tracker import QuotaTracker


def simulate_quota_evacuation():
    print("\n" + "=" * 70)
    print("SCENARIO 4: PREEMPTIVE RATE-LIMIT DETECTION & AUTO-EVACUATION HANDOFF")
    print("=" * 70)

    test_dir = Path("./tmp_scenario_quota").resolve()
    agent_a_dir = test_dir / "agent_a_workspace"
    agent_b_dir = test_dir / "agent_b_workspace"
    shared_store = test_dir / "capsule_store"

    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)

    agent_a_dir.mkdir(parents=True, exist_ok=True)
    agent_b_dir.mkdir(parents=True, exist_ok=True)
    shared_store.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Agent A creates half-completed work
        (agent_a_dir / "payment_gateway.py").write_text(
            "# Stripe payment processor\ndef process_payment(amount):\n    # TODO: add webhook verification\n    return {'status': 'processed', 'amount': amount}\n",
            encoding="utf-8",
        )
        (agent_a_dir / "test_payment.py").write_text(
            "def test_payment():\n    assert True\n",
            encoding="utf-8",
        )

        store_a = CapsuleStore(base_dir=shared_store)
        tracker_a = QuotaTracker(data_path=test_dir)
        guard_a = QuotaGuard(workspace_path=agent_a_dir, tracker=tracker_a, store=store_a)

        # 2. Simulate heavy API traffic on Anthropic Claude
        print("[Agent A: Claude] Executing complex multi-step refactoring on 'PAY-701'...")
        print("[Agent A: Claude] Receiving Anthropic API responses with rate-limit telemetry...")

        simulated_anthropic_headers = {
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "1",  # Imminent exhaustion!
            "anthropic-ratelimit-requests-reset": "2026-09-20T23:00:00Z",
            "anthropic-ratelimit-tokens-limit": "200000",
            "anthropic-ratelimit-tokens-remaining": "8500",
        }

        # 3. Record response headers into QuotaGuard
        quota_status = guard_a.record_interaction(
            provider="anthropic",
            tokens_used=45000,
            requests_used=1,
            headers=simulated_anthropic_headers,
        )

        print(f"[QuotaGuard] Provider 'Anthropic' Status: {quota_status.reason}")
        print(f"[QuotaGuard] Remaining requests: {quota_status.remaining_requests} | Critical threshold breached!")

        # 4. Preemptive Evacuation Triggered
        print("[QuotaGuard] Freezing Agent A session BEFORE 429 hard lockout...")
        evac_result = guard_a.evacuate_if_needed(
            task_id="PAY-701",
            provider="anthropic",
            title="Stripe Payment Webhooks Refactor",
            summary="Implemented process_payment; webhook signature verification pending.",
            next_action="Complete webhook verification and run test_payment.py",
            target_provider="gemini",
        )

        assert evac_result.evacuated, "QuotaGuard should have automatically evacuated the session!"
        print(f"[QuotaGuard] Preemptive Capsule Generated: {evac_result.capsule_id}")
        print(f"[QuotaGuard] Recommended Successor: '{evac_result.target_provider}'")

        # 5. Agent B (Gemini / Secondary Account) takes over
        print("\n[Agent B: Gemini] Successor agent activates to assume task 'PAY-701'...")
        store_b = CapsuleStore(base_dir=shared_store)
        capsule_for_b = store_b.load_by_id(evac_result.capsule_id)
        assert capsule_for_b is not None

        unpacker_b = CapsuleUnpacker(workspace_path=agent_b_dir)
        restoration = unpacker_b.apply(capsule_for_b, apply_workspace=True)

        print(f"[Agent B: Gemini] Restored workspace files: {', '.join(restoration['untracked_files_restored'])}")
        assert (agent_b_dir / "payment_gateway.py").exists()
        assert (agent_b_dir / "test_payment.py").exists()

        print("[Agent B: Gemini] Resumption prompt received:")
        print(f"  > \"{capsule_for_b.resumption_prompt}\"")

        print("\n[+] SUCCESS: Rate limit intercepted and task handed off seamlessly to successor provider!")
        print("=" * 70 + "\n")

    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    simulate_quota_evacuation()
