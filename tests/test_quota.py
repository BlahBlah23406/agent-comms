"""
Unit Tests for Quota Guard & Preemptive Rate-Limit Evacuation
============================================================
Tests QuotaTracker header parsing, usage accumulation, threshold evaluation,
and QuotaGuard preemptive Context Capsule generation for seamless handoff.
"""

import json
import unittest
from pathlib import Path
import shutil

from agent_comms.capsule.store import CapsuleStore
from agent_comms.quota.guard import QuotaGuard
from agent_comms.quota.models import AIProvider, QuotaBudget, QuotaWindow
from agent_comms.quota.tracker import QuotaTracker


class TestQuotaGuard(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path("./tmp_test_quota").resolve()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.tracker = QuotaTracker(data_path=self.temp_dir)
        self.store = CapsuleStore(base_dir=self.temp_dir / "capsules")
        self.guard = QuotaGuard(
            workspace_path=self.temp_dir,
            tracker=self.tracker,
            store=self.store,
        )

        # Create dummy workspace file
        (self.temp_dir / "app.py").write_text("print('Work in progress')", encoding="utf-8")

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_usage_tracking_and_budget(self):
        """Tests manual usage recording and budget utilization math."""
        self.tracker.set_budget(
            QuotaBudget(
                provider="test-provider",
                window=QuotaWindow.HOUR,
                max_requests=10,
                max_tokens=1000,
                warning_threshold_ratio=0.70,
                critical_threshold_ratio=0.90,
                min_safe_requests_remaining=2,
                min_safe_tokens_remaining=100,
            )
        )

        # 1. Healthy state
        self.tracker.record_usage("test-provider", tokens=200, requests=2)
        st = self.tracker.get_status("test-provider")
        self.assertEqual(st.requests_used, 2)
        self.assertEqual(st.tokens_used, 200)
        self.assertFalse(st.is_warning)
        self.assertFalse(st.recommend_evacuation)

        # 2. Warning state (70% utilization)
        self.tracker.record_usage("test-provider", tokens=550, requests=5)
        st_warn = self.tracker.get_status("test-provider")
        self.assertTrue(st_warn.is_warning)
        self.assertFalse(st_warn.recommend_evacuation)

        # 3. Critical state (9 requests used, only 1 safe request remaining)
        self.tracker.record_usage("test-provider", tokens=200, requests=2)
        st_crit = self.tracker.get_status("test-provider")
        self.assertTrue(st_crit.is_critical)
        self.assertTrue(st_crit.recommend_evacuation)

    def test_anthropic_header_parsing(self):
        """Tests parsing real Anthropic rate-limit headers."""
        headers = {
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "2",  # Below min safe requests (3)
            "anthropic-ratelimit-requests-reset": "2026-09-20T22:00:00Z",
            "anthropic-ratelimit-tokens-limit": "200000",
            "anthropic-ratelimit-tokens-remaining": "15000",
            "anthropic-ratelimit-tokens-reset": "2026-09-20T22:00:00Z",
        }

        self.guard.record_interaction("anthropic", headers=headers)
        status = self.guard.check_quota("anthropic")

        self.assertEqual(status.remaining_requests, 2)
        self.assertEqual(status.reset_at, "2026-09-20T22:00:00Z")
        self.assertTrue(status.is_critical)
        self.assertTrue(status.recommend_evacuation)
        self.assertIn("only 2 request(s) remaining", status.reason)

    def test_openai_header_parsing_and_retry_after(self):
        """Tests parsing OpenAI headers and Retry-After 429 response."""
        headers = {
            "x-ratelimit-limit-requests": "100",
            "x-ratelimit-remaining-requests": "0",
            "retry-after": "45",
        }

        self.guard.record_interaction("openai", headers=headers, status_code=429)
        status = self.guard.check_quota("openai")

        self.assertTrue(status.is_rate_limited)
        self.assertTrue(status.recommend_evacuation)
        self.assertEqual(status.retry_after_seconds, 45.0)

    def test_preemptive_evacuation_capsule_generation(self):
        """
        Tests that when rate limit is imminent, evacuate_if_needed creates a high-fidelity
        Context Capsule capturing workspace diffs, epistemic learning, and handoff instructions.
        """
        # Set Anthropic to critical threshold via headers
        headers = {
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "1",  # Imminent limit
            "anthropic-ratelimit-requests-reset": "2026-09-20T22:00:00Z",
        }
        self.guard.record_interaction("anthropic", headers=headers)

        # Trigger preemptive evacuation
        result = self.guard.evacuate_if_needed(
            task_id="TICKET-RATE-LIMIT-101",
            provider="anthropic",
            summary="Completed auth module; test suite pending.",
            next_action="Run pytest test_auth.py with alternative provider",
            target_provider="gemini",
        )

        self.assertTrue(result.evacuated)
        self.assertEqual(result.task_id, "TICKET-RATE-LIMIT-101")
        self.assertEqual(result.provider, "anthropic")
        self.assertEqual(result.target_provider, "gemini")
        self.assertIsNotNone(result.capsule_id)

        # Verify capsule was stored and is valid
        capsule = self.store.load_by_id(result.capsule_id)
        self.assertIsNotNone(capsule)
        self.assertEqual(capsule.task_id, "TICKET-RATE-LIMIT-101")

        # Verify epistemic learning mentions the rate limit
        rate_limit_learnings = [
            l for l in capsule.epistemic_learnings if "Preemptive Quota Evacuation" in l.summary
        ]
        self.assertEqual(len(rate_limit_learnings), 1)
        self.assertIn("anthropic", rate_limit_learnings[0].details)

        # Verify untracked workspace file was captured
        self.assertIn("app.py", capsule.workspace.untracked_files)

        # Verify resumption prompt guides successor agent
        self.assertIn("gemini", capsule.resumption_prompt or "")

    def test_session_watchdog_auto_evacuation(self):
        """Tests that SessionWatchdog detects rate-limit pause in a Claude session log and evacuates."""
        from agent_comms.quota.watchdog import SessionWatchdog

        # Create a simulated Claude Code session log
        sim_log = self.temp_dir / "sim_session.jsonl"
        log_lines = [
            json.dumps({"type": "user", "cwd": str(self.temp_dir), "sessionId": "session-test-888"}),
            json.dumps({"type": "user", "lastPrompt": "Write the audio dubbing pipeline"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Implemented mixer and audio sync."}]}}),
            json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "<command-name>/rate-limit-options</command-name>\n<local-command-stdout>Claude Code will continue automatically at 6:50pm. Press esc to cancel.</local-command-stdout>"
                }
            }),
        ]
        sim_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

        watchdog = SessionWatchdog()
        info = watchdog.scan_session_file(sim_log)

        self.assertIsNotNone(info)
        self.assertEqual(info["session_id"], "session-test-888")
        self.assertEqual(Path(info["workspace_dir"]).resolve(), self.temp_dir.resolve())
        self.assertIn("rate-limit-options", info["trigger"].lower())

        # Test evacuation
        res = watchdog.evacuate(info)
        self.assertIsNotNone(res)
        self.assertTrue(res.evacuated)
        self.assertIsNotNone(res.capsule_id)

        # Verify briefing file created in workspace
        briefing_file = self.temp_dir / "PREEMPTIVE_EVACUATION_BRIEFING.md"
        self.assertTrue(briefing_file.exists())
        self.assertIn(res.capsule_id, briefing_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
