import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_comms.capsule.store import CapsuleStore
from agent_comms.config import config_manager
from agent_comms.fleet import capacity, remote, runner, tick
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

        with patch.object(config_manager, "config_dir", cfg_dir), patch.object(
            config_manager, "get", return_value=None
        ), patch.object(Path, "home", return_value=self.temp_dir):
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
        ), patch.object(capacity, "check", return_value={"busy": False, "reason": None}):
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

    def test_runner_pick_avoids_caller_despite_fewer_runs(self):
        now = time.time()
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex", "agy"]
        ), patch.object(runner.capacity, "check", return_value={"busy": False}):
            runner.save_usage({
                "runs": {"claude": [], "codex": [now], "agy": [now, now]},
                "cooldown": {},
            })
            self.assertEqual(runner.pick(), "claude")
            self.assertEqual(runner.pick(avoid={"claude"}), "codex")

    def test_runner_submit_spreads_prompts_across_providers(self):
        prompts = ["First task", "Second task", "Third task"]
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex", "agy"]
        ), patch.object(runner.capacity, "check", return_value={"busy": False}), patch.object(
            runner.subprocess, "Popen"
        ) as popen:
            jobs = runner.submit(prompts, cwd=str(self.temp_dir), caller="claude")

            self.assertEqual(len(jobs), 3)
            self.assertEqual({job["agent"] for job in jobs}, {"claude", "codex", "agy"})
            self.assertNotEqual(jobs[0]["agent"], "claude")
            self.assertEqual([job["prompt"] for job in jobs], prompts)
            self.assertTrue(all(job["caller"] == "claude" for job in jobs))
            self.assertEqual(popen.call_count, 3)
            for job, call in zip(jobs, popen.call_args_list):
                self.assertEqual(runner.read_job(job["id"]), job)
                self.assertEqual(call.args[0][-1], job["id"])

    def test_runner_detect_caller_from_client_name(self):
        with patch.dict(os.environ, {}, clear=True):
            for client, expected in (
                ("claude-code", "claude"),
                ("codex-mcp-client", "codex"),
                ("Antigravity", "agy"),
            ):
                with self.subTest(client=client):
                    self.assertEqual(runner.detect_caller(client), expected)

    def test_autosave_force_saves_on_first_turn_without_incrementing(self):
        payload = {"cwd": str(self.temp_dir), "session_id": "force-session"}
        store = MagicMock()
        store.base_dir = self.temp_dir / "capsules"
        capsule = MagicMock(task_id="auto-test")
        capsule.extra_metadata = {}
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            Path, "home", return_value=self.temp_dir
        ), patch("agent_comms.fleet.autosave.CapsulePackager") as packager:
            packager.return_value.package.return_value = capsule
            self.assertIsNone(autosave(payload, agent="claude", every=2, store=store))
            turns_file = self.temp_dir / "turns.json"
            counter_before = turns_file.read_bytes()
            self.assertEqual(json.loads(counter_before), {"force-session": 1})

            saved = autosave(payload, agent="claude", every=2, store=store, force=True)

            self.assertIs(saved, capsule)
            packager.return_value.package.assert_called_once()
            store.save.assert_called_once_with(capsule)
            self.assertTrue(capsule.extra_metadata["autosave"])
            self.assertEqual(turns_file.read_bytes(), counter_before)

    def test_tick_starts_save_once_per_ten_minutes_for_same_session(self):
        raw = json.dumps({"session_id": "tick-session", "cwd": str(self.temp_dir)})
        with patch.object(Path, "home", return_value=self.temp_dir), patch.object(
            sys, "argv", ["tick", "codex"]
        ), patch.object(sys, "stdout", new_callable=io.StringIO), patch.object(
            tick.time, "time", side_effect=[10000, 10599, 10600]
        ), patch.object(tick.subprocess, "Popen") as popen:
            for expected_calls in (1, 1, 2):
                with patch.object(sys, "stdin", io.StringIO(raw)):
                    tick.main()
                self.assertEqual(popen.call_count, expected_calls)

            command = popen.call_args.args[0]
            self.assertEqual(command[:-1], [
                sys.executable, "-m", "agent_comms.cli", "autosave",
                "--agent", "codex", "--force", "--payload",
            ])
            self.assertEqual(Path(command[-1]).read_text(encoding="utf-8"), raw)
            state = json.loads((self.temp_dir / ".agent-comms" / "saves.json").read_text())
            self.assertEqual(state, {"tick-session": 10600})

    def test_runner_take_patch_applies_remote_changes(self):
        workspace = self.temp_dir / "workspace"
        workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(workspace)], check=True, capture_output=True)
        target = workspace / "example.txt"
        target.write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "example.txt"], cwd=workspace, check=True, capture_output=True)
        target.write_text("after\n", encoding="utf-8")
        diff = subprocess.run(
            ["git", "diff", "--", "example.txt"], cwd=workspace,
            check=True, capture_output=True, text=True,
        ).stdout
        self.assertTrue(diff)
        target.write_text("before\n", encoding="utf-8")
        output = f"Helper summary\n{remote.PATCH_START}\n{diff}{remote.PATCH_END}\nDone"

        with patch.object(config_manager, "config_dir", self.temp_dir):
            result = runner._take_patch({"id": "patch-job", "cwd": str(workspace)}, output)

        self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
        self.assertEqual((self.temp_dir / "jobs" / "patch-job.patch").read_text(), diff)
        self.assertIn("Helper summary", result)
        self.assertIn("Done", result)
        self.assertIn("file changes from the helper were applied", result)
        self.assertNotIn(remote.PATCH_START, result)
        self.assertNotIn(remote.PATCH_END, result)

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
            self.assertEqual(ps_cmd[:9], ["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "LogLevel=ERROR", "user@win"])
            self.assertTrue(ps_cmd[9].startswith("agent-comms remote-run "))
            ps_spec = json.loads(base64.b64decode(ps_cmd[9].split()[-1]))
            self.assertEqual(ps_spec["folder"], "C:\\work\\it's_here")
            self.assertEqual(ps_spec["cmd"], ["claude", "-p", "--permission-mode", "auto", "fix it's bug"])

            sh_cmd = runner.build_command("claude@linuxbox", "fix bug", "/tmp", "capsule-1")
            self.assertEqual(sh_cmd[:9], ["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "LogLevel=ERROR", "user@linux"])
            self.assertIn('exec "${SHELL:-sh}" -lc ', sh_cmd[9])
            self.assertIn("export PATH=", sh_cmd[9])
            sh_spec = json.loads(base64.b64decode(sh_cmd[9].rstrip("'").split()[-1]))
            self.assertEqual(sh_spec["folder"], "~/proj")
            self.assertEqual(sh_spec["capsule"], "capsule-1")
            self.assertEqual(sh_spec["cmd"][-1], "fix bug")

    def test_capacity_check(self):
        with patch.object(capacity, "cpu_percent", return_value=20.0), patch.object(
            capacity, "free_memory_mb", return_value=4096.0
        ), patch.object(capacity, "running_agents", return_value=2), patch.object(
            config_manager, "get", return_value=None
        ):
            res = capacity.check()
            self.assertFalse(res["busy"])
            self.assertIsNone(res["reason"])

        with patch.object(capacity, "cpu_percent", return_value=90.0), patch.object(
            capacity, "free_memory_mb", return_value=4096.0
        ), patch.object(capacity, "running_agents", return_value=2), patch.object(
            config_manager, "get", return_value=None
        ):
            res = capacity.check()
            self.assertTrue(res["busy"])
            self.assertIn("CPU", res["reason"])

        with patch.object(capacity, "cpu_percent", return_value=20.0), patch.object(
            capacity, "free_memory_mb", return_value=512.0
        ), patch.object(capacity, "running_agents", return_value=2), patch.object(
            config_manager, "get", return_value=None
        ):
            res = capacity.check()
            self.assertTrue(res["busy"])
            self.assertIn("free memory", res["reason"])

        with patch.object(capacity, "cpu_percent", return_value=20.0), patch.object(
            capacity, "free_memory_mb", return_value=4096.0
        ), patch.object(capacity, "running_agents", return_value=6), patch.object(
            config_manager, "get", return_value=None
        ):
            res = capacity.check()
            self.assertTrue(res["busy"])
            self.assertIn("helper jobs", res["reason"])

        with patch.object(capacity, "cpu_percent", return_value=20.0), patch.object(
            capacity, "free_memory_mb", return_value=4096.0
        ), patch.object(capacity, "running_agents", return_value=2), patch.object(
            config_manager, "get", side_effect=lambda k, default=None: False if k == "accept_work" else default
        ):
            res = capacity.check()
            self.assertTrue(res["busy"])
            self.assertIn("switched off", res["reason"])

    def test_runner_pick_skips_local_when_busy(self):
        cfg_dir = self.temp_dir / "config"
        cfg_dir.mkdir(exist_ok=True)
        with patch.object(config_manager, "config_dir", cfg_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex", "agy@box"]
        ), patch.object(
            capacity, "check", return_value={"busy": True, "reason": "CPU at 95% (cap 85%)"}
        ):
            runner.save_usage({"runs": {}, "cooldown": {}})
            self.assertEqual(runner.pick(), "agy@box")

    def test_runner_work_moves_to_next_slot_on_exit_75(self):
        cfg_dir = self.temp_dir / "config"
        cfg_dir.mkdir(exist_ok=True)
        cwd = self.temp_dir / "work"
        cwd.mkdir(exist_ok=True)

        def fake_build_command(slot, prompt, job_cwd, capsule_id=None, snapshot=False):
            if slot == "claude@box1":
                return [sys.executable, "-c", 'import sys; print("BUSY: test"); sys.exit(75)']
            return [sys.executable, "-c", 'print("ok")']

        with patch.object(config_manager, "config_dir", cfg_dir), patch.object(
            runner, "available_slots", return_value=["claude@box1", "codex@box2"]
        ), patch.object(
            runner, "pick", return_value="codex@box2"
        ), patch.object(
            runner, "build_command", side_effect=fake_build_command
        ):
            job = {
                "id": "job75",
                "prompt": "test prompt",
                "agent": "claude@box1",
                "cwd": str(cwd),
                "status": "queued",
                "tried": [],
                "created": time.time(),
                "caller": None,
            }
            runner.write_job(job)
            runner.work("job75")
            final_job = runner.read_job("job75")
            self.assertEqual(final_job["status"], "done")
            self.assertEqual(final_job["exit_code"], 0)
            self.assertEqual(final_job["tried"], ["claude@box1", "codex@box2"])


if __name__ == "__main__":
    unittest.main()
