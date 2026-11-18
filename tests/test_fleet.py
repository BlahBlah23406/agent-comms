import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_comms.capsule.store import CapsuleStore
from agent_comms.config import config_manager
from agent_comms.fleet import runner
from agent_comms.fleet.autosave import autosave, read_transcript


class TestFleet(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="agent_comms_test_fleet_")).resolve()

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_transcript_claude_jsonl(self):
        path = self.temp_dir / "claude.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"content": "Fix the bug"}}),
            json.dumps({"type": "user", "message": {"content": "<command-name>/clear</command-name>"}}),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_result", "text": "ignored tool output"},
                        {"type": "text", "text": "Working on it."},
                    ]
                },
            }),
            json.dumps({
                "type": "user",
                "message": {"content": [{"type": "tool_result", "text": "only tool result"}]},
            }),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        messages, tail = read_transcript(str(path))
        self.assertEqual(messages, [("user", "Fix the bug"), ("assistant", "Working on it.")])
        self.assertIn("only tool result", tail)

    def test_read_transcript_codex_jsonl(self):
        path = self.temp_dir / "codex.jsonl"
        lines = [
            json.dumps({
                "type": "response_item",
                "payload": {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Add tests"}],
                },
            }),
            json.dumps({
                "type": "response_item",
                "payload": {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Tests added."}],
                },
            }),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        messages, _ = read_transcript(str(path))
        self.assertEqual(messages, [("user", "Add tests"), ("assistant", "Tests added.")])

    def test_read_transcript_gemini_json(self):
        path = self.temp_dir / "gemini.json"
        data = {
            "messages": [
                {"type": "user", "content": [{"text": "Explain fleet"}]},
                {"type": "gemini", "content": "Fleet distributes tasks."},
            ]
        }
        path.write_text(json.dumps(data), encoding="utf-8")

        messages, _ = read_transcript(str(path))
        self.assertEqual(messages, [("user", "Explain fleet"), ("assistant", "Fleet distributes tasks.")])

    def test_read_transcript_agy_jsonl(self):
        path = self.temp_dir / "agy.jsonl"
        lines = [
            json.dumps({
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nFix the bug\n</USER_REQUEST>\n<ADDITIONAL_METADATA>time</ADDITIONAL_METADATA>",
            }),
            json.dumps({"type": "GENERIC", "content": "tool output"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "Fixed it."}),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        messages, _ = read_transcript(str(path))
        self.assertEqual(messages, [("user", "Fix the bug"), ("assistant", "Fixed it.")])

    def test_autosave_every_second_turn_and_immediate_on_limit(self):
        cfg_dir = self.temp_dir / "config"
        cfg_dir.mkdir()
        store = CapsuleStore(base_dir=self.temp_dir / "capsules")
        cwd = self.temp_dir / "workspace"
        cwd.mkdir()

        with patch.object(config_manager, "config_dir", cfg_dir):
            payload = {"cwd": str(cwd), "session_id": "sess-1", "prompt": "Step 1"}

            c1 = autosave(payload, agent="claude", every=2, store=store)
            self.assertIsNone(c1)

            c2 = autosave(payload, agent="claude", every=2, store=store)
            self.assertIsNotNone(c2)
            self.assertEqual(c2.extra_metadata["turn"], 2)
            self.assertFalse(c2.extra_metadata["hit_limit"])

            limit_payload = {
                "cwd": str(cwd),
                "session_id": "sess-1",
                "prompt": "Step 3",
                "last_assistant_message": "You have reached your usage limit for this plan.",
            }
            c3 = autosave(limit_payload, agent="claude", every=2, store=store)
            self.assertIsNotNone(c3)
            self.assertEqual(c3.extra_metadata["turn"], 3)
            self.assertTrue(c3.extra_metadata["hit_limit"])

    def test_runner_pick_fewest_runs_and_skips_resting(self):
        cfg_dir = self.temp_dir / "config"
        cfg_dir.mkdir()
        now = time.time()

        with patch.object(config_manager, "config_dir", cfg_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex", "gemini"]
        ):
            runner.save_usage({
                "runs": {
                    "claude": [now - 10, now - 5],
                    "codex": [now - 10],
                    "gemini": [],
                },
                "cooldown": {
                    "gemini": now + 1800,
                },
            })
            self.assertEqual(runner.pick(), "codex")

    def test_build_command_powershell_and_normal_host(self):
        hosts = [
            {"name": "winbox", "ssh": "user@win", "dir": "C:\\work\\it's_here", "shell": "powershell"},
            {"name": "linuxbox", "ssh": "user@linux", "dir": "~/proj"},
        ]

        def fake_get(key, default=None):
            if key == "fleet_hosts":
                return hosts
            if key == "fleet_permissions":
                return "edits"
            return default

        with patch.object(config_manager, "get", side_effect=fake_get):
            ps_cmd = runner.build_command("claude@winbox", "fix it's bug", "/tmp")
            self.assertEqual(ps_cmd[:3], ["ssh", "-o", "BatchMode=yes"])
            self.assertEqual(ps_cmd[3], "user@win")
            self.assertEqual(
                ps_cmd[4],
                "cd 'C:\\work\\it''s_here'; & 'claude' '-p' '--permission-mode' 'acceptEdits' 'fix it''s bug'",
            )

            sh_cmd = runner.build_command("claude@linuxbox", "fix bug", "/tmp")
            self.assertEqual(sh_cmd[:4], ["ssh", "-o", "BatchMode=yes", "user@linux"])
            self.assertEqual(
                sh_cmd[4],
                "cd ~/proj && claude -p --permission-mode acceptEdits 'fix bug'",
            )


if __name__ == "__main__":
    unittest.main()
