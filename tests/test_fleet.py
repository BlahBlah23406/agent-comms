import base64
import io
import json
import multiprocessing
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
from agent_comms.fleet import capacity, install, remote, runner, tick
from agent_comms.fleet.autosave import autosave, read_transcript


def _record_runs_in_process(config_dir, start, count):
    with patch.object(config_manager, "config_dir", Path(config_dir)):
        if not start.wait(10):
            raise RuntimeError("Timed out waiting for concurrent writers")
        for _ in range(count):
            runner._record_run("claude@box")


class TestFleet(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="agent_comms_test_fleet_")).resolve()
        self._saved_helper_env = os.environ.pop(runner.HELPER_ENV, None)

    def tearDown(self):
        if self._saved_helper_env is not None:
            os.environ[runner.HELPER_ENV] = self._saved_helper_env
        else:
            os.environ.pop(runner.HELPER_ENV, None)
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
            # The caller's own provider is kept free while others can take work; the rest take turns.
            self.assertEqual({job["agent"] for job in jobs}, {"codex", "agy"})
            self.assertNotEqual(jobs[0]["agent"], jobs[1]["agent"])
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
            ps_spec = json.loads(base64.b64decode(ps_cmd[9].split("remote-run ")[1].split(";")[0]))
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

    def test_capacity_counts_only_live_local_and_incoming_jobs(self):
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "_alive", side_effect=lambda pid: pid in (101, 102)
        ):
            for job_id, status, agent, pid in (
                ("local", "running", "claude", 101),
                ("dead", "running", "codex", 999),
                ("remote", "running", "claude@box", 101),
                ("queued", "queued", "claude", 101),
                ("done", "done", "codex", 101),
                ("no-pid", "running", "claude", None),
            ):
                runner.write_job({"id": job_id, "status": status, "agent": agent, "pid": pid})
            jobs_dir = self.temp_dir / "jobs"
            (jobs_dir / "invalid.json").write_text("not json", encoding="utf-8")
            live_marker = jobs_dir / "incoming-102.pid"
            dead_marker = jobs_dir / "incoming-999.pid"
            live_marker.touch()
            dead_marker.touch()

            self.assertEqual(capacity.running_agents(), 2)
            self.assertTrue(live_marker.exists())
            self.assertFalse(dead_marker.exists())
            self.assertEqual(capacity.running_agents(), 2)

    def test_runner_ssh_env_recovers_launchd_socket_only_when_missing(self):
        with patch.dict(os.environ, {"PATH": "/test/bin"}, clear=True), patch.object(
            runner.platform, "system", return_value="Darwin"
        ), patch.object(runner.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=" /tmp/launchd.sock\n")
            env = runner._ssh_env()
            self.assertEqual(env["SSH_AUTH_SOCK"], "/tmp/launchd.sock")
            self.assertEqual(env["PATH"], "/test/bin")
            self.assertNotIn("SSH_AUTH_SOCK", os.environ)
            run.assert_called_once_with(
                ["launchctl", "getenv", "SSH_AUTH_SOCK"], capture_output=True, text=True, timeout=5
            )

        with patch.dict(os.environ, {"SSH_AUTH_SOCK": "/tmp/existing.sock"}, clear=True), patch.object(
            runner.platform, "system", return_value="Darwin"
        ), patch.object(runner.subprocess, "run") as run:
            self.assertEqual(runner._ssh_env()["SSH_AUTH_SOCK"], "/tmp/existing.sock")
            run.assert_not_called()

    def test_runner_work_rests_unreachable_host_and_finishes_on_next_slot(self):
        now = 10000
        slots = ["claude@offline", "codex@offline", "agy@online"]

        def fake_run(command, **kwargs):
            failed = command == [slots[0]]
            kwargs["stdout"].write("ssh: connection refused" if failed else "finished")
            return subprocess.CompletedProcess(command, 255 if failed else 0)

        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            config_manager, "get", return_value=None
        ), patch.object(runner, "available_slots", return_value=slots), patch.object(
            runner.time, "time", return_value=now
        ), patch.object(runner, "_share_state", return_value=None), patch.object(
            remote, "snapshot", return_value=None
        ), patch.object(runner, "_ssh_env", return_value={}), patch.object(
            runner, "build_command", side_effect=lambda slot, *args, **kwargs: [slot]
        ), patch.object(runner.subprocess, "run", side_effect=fake_run) as run:
            runner.write_job({
                "id": "unreachable", "prompt": "test", "agent": slots[0],
                "cwd": str(self.temp_dir), "status": "queued", "tried": [], "created": now,
            })
            runner.work("unreachable")
            job = runner.read_job("unreachable")
            usage = runner.load_usage()

            self.assertEqual(job["status"], "done")
            self.assertEqual(job["exit_code"], 0)
            self.assertEqual(job["agent"], slots[2])
            self.assertEqual(job["output"], "finished")
            self.assertEqual(job["tried"], slots)
            self.assertEqual(job["attempts"], [{
                "agent": slots[0], "exit_code": 255, "error": "ssh: connection refused",
            }])
            self.assertEqual(usage["cooldown"], {
                slot: now + runner.UNREACHABLE_SECONDS for slot in slots[:2]
            })
            self.assertEqual(usage["runs"][slots[2]], [now])
            self.assertEqual([call.args[0] for call in run.call_args_list], [[slots[0]], [slots[2]]])

    def test_runner_work_zero_exit_sandbox_error_is_failed_and_explained(self):
        now = 10000
        output = "bwrap: setting up uid map: Operation not permitted"

        def fake_run(command, **kwargs):
            kwargs["stdout"].write(output)
            return subprocess.CompletedProcess(command, 0)

        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            config_manager, "get", return_value=None
        ), patch.object(runner, "available_slots", return_value=["codex"]), patch.object(
            runner.time, "time", return_value=now
        ), patch.object(runner, "build_command", return_value=["fake-codex"]), patch.object(
            runner.subprocess, "run", side_effect=fake_run
        ):
            runner.write_job({
                "id": "sandbox", "prompt": "test", "agent": "codex",
                "cwd": str(self.temp_dir), "status": "queued", "tried": [], "created": now,
            })
            runner.work("sandbox")
            job = runner.read_job("sandbox")
            usage = runner.load_usage()
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["exit_code"], 1)
            self.assertEqual(job["attempts"], [{"agent": "codex", "exit_code": 1, "error": output}])
            self.assertEqual(usage["cooldown"]["codex"], now + runner.BROKEN_SECONDS)
            self.assertIn("sandbox", usage["reason"]["codex"])
            row, = runner.status()
            self.assertIsNotNone(row["resting_until"])
            self.assertEqual(row["why"], usage["reason"]["codex"])

    def test_runner_submit_own_provider_uses_another_and_explains(self):
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex"]
        ), patch.object(capacity, "check", return_value={"busy": False}), patch.object(
            runner.subprocess, "Popen"
        ) as popen:
            job, = runner.submit(["test"], cwd=str(self.temp_dir), caller="claude", agent="claude")
            self.assertEqual(job["agent"], "codex")
            self.assertEqual(job["caller"], "claude")
            self.assertIn("own provider", job["note"])
            self.assertIn("other providers go first", job["note"])
            self.assertEqual(runner.read_job(job["id"]), job)
            popen.assert_called_once()

    def test_runner_check_stale_fails_running_job_with_dead_pid(self):
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "_alive", return_value=False
        ) as alive, patch.object(runner.time, "time", return_value=10000):
            job = {"id": "stale", "status": "running", "pid": 999, "output": "partial output"}
            runner.write_job(job)
            result = runner._check_stale(job)
            alive.assert_called_once_with(999)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["exit_code"], -1)
            self.assertEqual(result["finished"], 10000)
            self.assertIn("partial output", result["output"])
            self.assertIn("helper process stopped", result["output"])
            self.assertEqual(runner.read_job("stale"), result)

    def test_runner_pick_adds_provider_runs_across_hosts(self):
        now = time.time()
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude@a", "claude@b", "codex@a"]
        ):
            runner.save_usage({"runs": {
                "claude@a": [now], "claude@b": [now] * 4, "codex@a": [now] * 3,
            }, "cooldown": {}})
            self.assertEqual(runner.pick(), "codex@a")

    def test_remote_snapshot_round_trip_includes_untracked_excludes_ignored(self):
        workspace = self.temp_dir / "workspace"
        workspace.mkdir()
        with patch.object(config_manager, "config_dir", self.temp_dir):
            remote._git(workspace, "init", "-q", check=True)
            (workspace / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (workspace / "tracked.txt").write_text("original\n", encoding="utf-8")
            remote._git(workspace, "add", "-A", check=True)
            remote._git(workspace, "commit", "-qm", "initial", check=True)
            (workspace / "tracked.txt").write_text("edited\n", encoding="utf-8")
            (workspace / "untracked.txt").write_text("new file\n", encoding="utf-8")
            (workspace / "ignored.txt").write_text("ignored\n", encoding="utf-8")

            data = remote.snapshot(workspace)
            self.assertIsNotNone(data)
            tree = remote._snapshot_tree(data)
            self.assertIsNotNone(tree)
            self.addCleanup(shutil.rmtree, tree, ignore_errors=True)
            self.assertNotEqual(tree, workspace)
            self.assertEqual((tree / "tracked.txt").read_text(), "edited\n")
            self.assertEqual((tree / "untracked.txt").read_text(), "new file\n")
            self.assertEqual((tree / ".gitignore").read_text(), "ignored.txt\n")
            self.assertFalse((tree / "ignored.txt").exists())
            self.assertEqual(remote._git(tree, "status", "--porcelain", check=True).stdout, "")
            self.assertEqual(remote._git(tree, "show", "HEAD:untracked.txt", check=True).stdout, "new file\n")

    def test_install_codex_server_options_once_and_idempotent(self):
        text = (
            '[mcp_servers.other]\ncommand = "other"\n\n'
            '[mcp_servers.agent-comms]\ncommand = "python"\n'
            '[mcp_servers.agent-comms.env]\nAGENT_COMMS_MACHINE_ALIAS = "test"\n'
        )
        for existing in ([], install.CODEX_OPTIONS[:1], install.CODEX_OPTIONS[1:], install.CODEX_OPTIONS):
            with self.subTest(existing=existing):
                before = text.replace(
                    '[mcp_servers.agent-comms]\n',
                    '[mcp_servers.agent-comms]\n' + ''.join(option + '\n' for option in existing),
                )
                result = install.codex_server_options(before)
                self.assertEqual(install.codex_server_options(result), result)
                body = result.split('[mcp_servers.agent-comms]\n')[1].split('\n[')[0]
                for option in install.CODEX_OPTIONS:
                    self.assertEqual(result.count(option), 1)
                    self.assertIn(option, body)
                self.assertIn('[mcp_servers.other]\ncommand = "other"', result)
                self.assertIn('[mcp_servers.agent-comms.env]\nAGENT_COMMS_MACHINE_ALIAS = "test"', result)

    def test_runner_record_run_preserves_all_runs_from_three_processes(self):
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        processes = [context.Process(
            target=_record_runs_in_process, args=(str(self.temp_dir), start, 20)
        ) for _ in range(3)]
        try:
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
            with patch.object(config_manager, "config_dir", self.temp_dir):
                runs = runner.load_usage()["runs"]["claude@box"]
                self.assertEqual(len(runs), 60)
                self.assertTrue(all(isinstance(timestamp, (int, float)) for timestamp in runs))
                self.assertFalse((self.temp_dir / "fleet_usage.lock").exists())
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

    def test_runner_pick_balances_by_minutes_worked(self):
        now = time.time()
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex"]
        ), patch.object(capacity, "check", return_value={"busy": False, "reason": None}):
            runner.save_usage({
                "runs": {
                    "claude": [now] * 2,
                    "codex": [now] * 5,
                },
                "minutes": {
                    "claude": [[now, 15.0], [now, 15.0]],
                    "codex": [[now, 3.0]],
                },
                "cooldown": {},
            })
            self.assertEqual(runner.pick(), "codex")

    def test_runner_record_minutes_caps_at_fleet_timeout(self):
        now = 10000.0
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            config_manager, "get", side_effect=lambda k, default=None: 600 if k == "fleet_timeout" else default
        ), patch.object(runner.time, "time", return_value=now):
            runner._record_minutes("claude", 3600)
            runner._record_minutes("claude", 120)
            usage = runner.load_usage()
            self.assertEqual(usage["minutes"]["claude"], [[now, 10.0], [now, 2.0]])

    def test_tick_near_limit_claude_codex_and_benign(self):
        claude_path = self.temp_dir / "claude_limit.jsonl"
        claude_path.write_text(
            json.dumps({
                "type": "user",
                "message": {"content": "[Usage limit reached; a short grace allowance remains to wrap up]"},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIsNotNone(tick.near_limit(str(claude_path)))

        codex_high = self.temp_dir / "codex_high.jsonl"
        codex_high.write_text(
            json.dumps({
                "type": "token_count",
                "rate_limits": {"primary": {"used_percent": 95}},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(tick.near_limit(str(codex_high)), "95% of the usage limit used")

        codex_low = self.temp_dir / "codex_low.jsonl"
        codex_low.write_text(
            json.dumps({
                "type": "token_count",
                "rate_limits": {"primary": {"used_percent": 14}},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(tick.near_limit(str(codex_low)))

        mid_sentence = self.temp_dir / "mid_sentence.jsonl"
        mid_sentence.write_text(
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": "The test checks how the parser handles a message when a usage limit reached error appears in logs."
                },
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(tick.near_limit(str(mid_sentence)))

    def test_tick_near_limit_ignores_short_assistant_mention(self):
        transcript = self.temp_dir / "assistant_mention.jsonl"
        transcript.write_text(
            json.dumps({
                "type": "assistant",
                "message": {"content": "The log says usage limit reached during the test."},
            }) + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(tick.near_limit(str(transcript)))

    def test_tick_main_immediate_save_on_near_limit_and_rate_limited(self):
        transcript = self.temp_dir / "codex_limit.jsonl"
        transcript.write_text(
            json.dumps({
                "type": "token_count",
                "rate_limits": {"primary": {"used_percent": 95}},
            }) + "\n",
            encoding="utf-8",
        )
        folder = self.temp_dir / ".agent-comms"
        folder.mkdir()
        (folder / "saves.json").write_text(json.dumps({"sess-limit": 9940}), encoding="utf-8")
        raw = json.dumps({
            "session_id": "sess-limit",
            "cwd": str(self.temp_dir),
            "transcript_path": str(transcript),
        })

        with patch.object(Path, "home", return_value=self.temp_dir), patch.object(
            sys, "argv", ["tick", "codex"]
        ), patch.object(sys, "stdout", new_callable=io.StringIO), patch.object(
            tick.time, "time", side_effect=[10000, 10100, 10599]
        ), patch.object(tick.subprocess, "Popen") as popen:
            with patch.object(sys, "stdin", io.StringIO(raw)):
                tick.main()
            self.assertEqual(popen.call_count, 1)
            payload_path = Path(popen.call_args.args[0][-1])
            saved_payload = json.loads(payload_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_payload["near_limit"], "95% of the usage limit used")
            self.assertIn("--force", popen.call_args.args[0])
            self.assertEqual(
                json.loads((folder / "saves.json").read_text(encoding="utf-8")),
                {"sess-limit": 10000, "limit:sess-limit": 10000},
            )

            for elapsed in (100, 599):
                with self.subTest(seconds_since_limit_save=elapsed), patch.object(
                    sys, "stdin", io.StringIO(raw)
                ):
                    tick.main()
                    self.assertEqual(popen.call_count, 1)

    def test_autosave_with_near_limit_marks_metadata(self):
        cfg_dir = self.temp_dir / "config"
        cfg_dir.mkdir()
        store = CapsuleStore(base_dir=self.temp_dir / "capsules")
        cwd = self.temp_dir / "workspace"
        cwd.mkdir()

        with patch.object(config_manager, "config_dir", cfg_dir), patch.object(
            config_manager, "get", return_value=None
        ), patch.object(Path, "home", return_value=self.temp_dir):
            payload = {
                "cwd": str(cwd),
                "session_id": "sess-near",
                "prompt": "Continue working on the feature",
                "near_limit": "95% of the usage limit used",
            }
            capsule = autosave(payload, agent="codex", every=2, store=store)
            self.assertIsNotNone(capsule)
            self.assertTrue(capsule.extra_metadata["hit_limit"])
            self.assertEqual(capsule.extra_metadata["near_limit"], "95% of the usage limit used")

    def test_install_refresh_if_outdated_runs_once_and_skips_when_current(self):
        state = {"machine_alias": "triskelion", "known_peers": ["code-47"]}

        def fake_get(k, default=None):
            return state.get(k, default)

        def fake_set(k, v):
            state[k] = v

        with patch.object(Path, "home", return_value=self.temp_dir), patch.object(
            config_manager, "get", side_effect=fake_get
        ), patch.object(
            config_manager, "set", side_effect=fake_set
        ), patch.object(install, "install_all") as mock_install_all:
            self.assertTrue(install.refresh_if_outdated(python="/usr/bin/python3"))
            mock_install_all.assert_called_once_with(
                self.temp_dir, "triskelion", ["code-47"], "/usr/bin/python3"
            )
            self.assertEqual(state["install_version"], install.INSTALL_VERSION)

            self.assertFalse(install.refresh_if_outdated(python="/usr/bin/python3"))
            mock_install_all.assert_called_once()

    def test_runner_submit_raises_when_helper_env_set(self):
        with patch.dict(os.environ, {runner.HELPER_ENV: "1"}), patch.object(
            config_manager, "config_dir", self.temp_dir
        ), patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "already a helper job"):
                runner.submit(["subtask"], cwd=str(self.temp_dir))
            popen.assert_not_called()
            self.assertFalse((self.temp_dir / "jobs").exists())

    def test_runner_submit_four_prompts_avoids_caller_and_alternates_codex_agy(self):
        prompts = ["task 1", "task 2", "task 3", "task 4"]
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude", "codex", "agy"]
        ), patch.object(runner.capacity, "check", return_value={"busy": False}), patch.object(
            runner.subprocess, "Popen"
        ):
            jobs = runner.submit(prompts, cwd=str(self.temp_dir), caller="claude")
            agents = [job["agent"] for job in jobs]
            self.assertNotIn("claude", agents)
            self.assertEqual(agents, ["codex", "agy", "codex", "agy"])

    def test_runner_pick_respects_host_max_jobs_default_and_configured(self):
        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            runner, "available_slots", return_value=["claude@box"]
        ), patch.object(runner.capacity, "check", return_value={"busy": False}):
            runner.write_job({"id": "j1", "agent": "claude@box", "status": "queued"})
            runner.write_job({"id": "j2", "agent": "codex@box", "status": "queued"})

            with patch.object(
                config_manager, "get",
                side_effect=lambda k, default=None: [{"name": "box", "agents": ["claude"]}] if k == "fleet_hosts" else default,
            ):
                self.assertIsNone(runner.pick())

            with patch.object(
                config_manager, "get",
                side_effect=lambda k, default=None: [{"name": "box", "agents": ["claude"], "max_jobs": 3}] if k == "fleet_hosts" else default,
            ):
                self.assertEqual(runner.pick(), "claude@box")

    def test_capacity_check_reserves_memory_per_running_job(self):
        with patch.object(capacity, "cpu_percent", return_value=10.0), patch.object(
            capacity, "free_memory_mb", return_value=1700.0
        ), patch.object(capacity, "running_agents", return_value=2), patch.object(
            config_manager, "get", return_value=None
        ):
            res = capacity.check()
            self.assertTrue(res["busy"])
            self.assertIn("free memory", res["reason"])
            self.assertIn("2 helper jobs running", res["reason"])

        with patch.object(capacity, "cpu_percent", return_value=10.0), patch.object(
            capacity, "free_memory_mb", return_value=1900.0
        ), patch.object(capacity, "running_agents", return_value=2), patch.object(
            config_manager, "get", return_value=None
        ):
            res = capacity.check()
            self.assertFalse(res["busy"])
            self.assertIsNone(res["reason"])

    def test_remote_run_admits_when_free_and_skips_marker_when_busy(self):
        encoded = remote.encode({"cmd": ["claude", "-p", "hi"], "folder": str(self.temp_dir)})
        marker = self.temp_dir / "jobs" / f"incoming-{os.getpid()}.pid"

        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            capacity, "check", return_value={"busy": True, "reason": "too busy"}
        ), patch.object(remote, "_run_here") as run_here, patch.object(
            sys, "stdout", new_callable=io.StringIO
        ) as out:
            self.assertEqual(remote.run(encoded), remote.BUSY_EXIT)
            run_here.assert_not_called()
            self.assertFalse(marker.exists())
            self.assertIn("BUSY: too busy", out.getvalue())

        seen_during_run = []

        def fake_run_here(spec):
            seen_during_run.append(marker.exists())
            return 0

        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            capacity, "check", return_value={"busy": False, "reason": None}
        ), patch.object(remote, "_run_here", side_effect=fake_run_here):
            self.assertEqual(remote.run(encoded), 0)
            self.assertEqual(seen_during_run, [True])
            self.assertFalse(marker.exists())

    def test_runner_work_treats_busy_prefix_with_exit_1_as_busy_host(self):
        now = 10000
        slots = ["claude@busybox", "codex@busybox", "agy@freebox"]

        def fake_run(command, **kwargs):
            is_busy = command == [slots[0]]
            kwargs["stdout"].write("BUSY: memory low\n" if is_busy else "done")
            return subprocess.CompletedProcess(command, 1 if is_busy else 0)

        with patch.object(config_manager, "config_dir", self.temp_dir), patch.object(
            config_manager, "get", return_value=None
        ), patch.object(runner, "available_slots", return_value=slots), patch.object(
            runner.time, "time", return_value=now
        ), patch.object(runner, "_share_state", return_value=None), patch.object(
            remote, "snapshot", return_value=None
        ), patch.object(runner, "_ssh_env", return_value={}), patch.object(
            runner, "build_command", side_effect=lambda slot, *args, **kwargs: [slot]
        ), patch.object(runner.subprocess, "run", side_effect=fake_run):
            runner.write_job({
                "id": "busy1", "prompt": "test", "agent": slots[0],
                "cwd": str(self.temp_dir), "status": "queued", "tried": [], "created": now,
            })
            runner.work("busy1")
            job = runner.read_job("busy1")
            usage = runner.load_usage()

            self.assertEqual(job["status"], "done")
            self.assertEqual(job["agent"], "agy@freebox")
            self.assertEqual(job["attempts"], [{
                "agent": "claude@busybox", "exit_code": runner.BUSY_EXIT, "error": "BUSY: memory low",
            }])
            self.assertEqual(usage["cooldown"], {
                "claude@busybox": now + runner.BUSY_SECONDS,
                "codex@busybox": now + runner.BUSY_SECONDS,
            })

    def test_runner_helper_limit_matches_start_of_line_not_quoted_mid_line(self):
        self.assertIsNotNone(runner.HELPER_LIMIT.search("■ You’ve hit your usage limit. Upgrade to Pro"))
        self.assertIsNotNone(runner.HELPER_LIMIT.search("You've hit your session limit · resets 5:50pm"))
        self.assertIsNone(
            runner.HELPER_LIMIT.search(
                "The helper checked whether 'You've hit your session limit · resets 5:50pm' matches."
            )
        )

    def test_build_command_powershell_ends_with_exit_lastexitcode(self):
        hosts = [{"name": "winbox", "ssh": "user@win", "dir": "C:\\work", "shell": "powershell"}]
        with patch.object(
            config_manager, "get",
            side_effect=lambda k, default=None: hosts if k == "fleet_hosts" else default,
        ):
            cmd = runner.build_command("claude@winbox", "run tests", "/tmp")
            self.assertTrue(cmd[-1].endswith("; exit $LASTEXITCODE"))


if __name__ == "__main__":
    unittest.main()
