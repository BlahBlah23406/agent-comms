"""
Fleet Runner
============
Hands tasks to the agent CLIs installed on this machine (and on SSH hosts),
spreading the work so no single subscription runs out first.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_comms.config import config_manager
from agent_comms.fleet import capacity
from agent_comms.fleet import remote
from agent_comms.fleet.autosave import hit_limit

COMMANDS = {
    "claude": {
        "auto": ["claude", "-p", "--permission-mode", "auto", "{prompt}"],
        "full": ["claude", "-p", "--dangerously-skip-permissions", "{prompt}"],
    },
    "codex": {
        "auto": ["codex", "exec", "-s", "workspace-write", "--skip-git-repo-check", "{prompt}"],
        "full": ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "{prompt}"],
    },
    "gemini": {
        "auto": ["gemini", "--approval-mode", "auto_edit", "-p", "{prompt}"],
        "full": ["gemini", "--yolo", "-p", "{prompt}"],
    },
    "agy": {
        "auto": ["agy", "--mode", "auto", "-p", "{prompt}"],
        "full": ["agy", "--dangerously-skip-permissions", "-p", "{prompt}"],
    },
    "ollama": {
        "auto": ["ollama", "run", "{model}", "{prompt}"],
        "full": ["ollama", "run", "{model}", "{prompt}"],
    },
}
DEFAULT_AGENTS = ["claude", "codex", "agy"]
WINDOW_SECONDS = 5 * 3600
COOLDOWN_SECONDS = 3600
BUSY_SECONDS = 600
BUSY_EXIT = remote.BUSY_EXIT
PATH_DIRS = "$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"
MAX_OUTPUT = 20000

WORKER_PREFIX = (
    "You are a helper agent working in the current project folder. Do only the task below, then stop. "
    "Other helpers may be editing other files at the same time, so only touch what this task needs. "
    "End with a short summary of what you changed.\n\nTask: {prompt}"
)


def detect_caller(client_name: str = "") -> Optional[str]:
    """Which provider is asking for help, so its own subscription is used last."""
    name = client_name.lower()
    for agent, hints in (("claude", ("claude",)), ("codex", ("codex",)), ("agy", ("antigravity", "agy", "jetski"))):
        if any(h in name for h in hints):
            return agent
    if os.environ.get("CLAUDECODE"):
        return "claude"
    if any(k.startswith("CODEX_") for k in os.environ):
        return "codex"
    if os.environ.get("ANTIGRAVITY_CONVERSATION_ID"):
        return "agy"
    return None


def _data_dir() -> Path:
    path = config_manager.config_dir / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _usage_file() -> Path:
    return config_manager.config_dir / "fleet_usage.json"


def load_usage() -> Dict[str, Any]:
    try:
        return json.loads(_usage_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"runs": {}, "cooldown": {}}


def save_usage(usage: Dict[str, Any]):
    _usage_file().write_text(json.dumps(usage, indent=2), encoding="utf-8")


def _record_run(slot: str):
    usage = load_usage()
    now = time.time()
    runs = [t for t in usage["runs"].get(slot, []) if now - t < WINDOW_SECONDS]
    usage["runs"][slot] = runs + [now]
    save_usage(usage)


def _cool_down(slot: str, seconds: int = COOLDOWN_SECONDS):
    usage = load_usage()
    usage["cooldown"][slot] = time.time() + seconds
    save_usage(usage)


def available_slots() -> List[str]:
    """Every agent we can use, written as 'agent' or 'agent@host'."""
    names = config_manager.get("fleet_agents") or DEFAULT_AGENTS
    slots = [n for n in names if n in COMMANDS and shutil.which(n)]
    for host in config_manager.get("fleet_hosts") or []:
        slots += [f"{a}@{host['name']}" for a in host.get("agents", []) if a in COMMANDS]
    return slots


def status() -> List[Dict[str, Any]]:
    usage = load_usage()
    now = time.time()
    rows = []
    for slot in available_slots():
        runs = [t for t in usage["runs"].get(slot, []) if now - t < WINDOW_SECONDS]
        cool = usage["cooldown"].get(slot, 0)
        rows.append({
            "agent": slot,
            "runs_last_5h": len(runs),
            "resting_until": time.strftime("%H:%M", time.localtime(cool)) if cool > now else None,
        })
    return rows


def pick(exclude: Optional[List[str]] = None, avoid: Optional[set] = None) -> Optional[str]:
    """Least-used free slot, trying providers in `avoid` (e.g. the caller's own) last."""
    rows = [r for r in status() if not r["resting_until"] and r["agent"] not in (exclude or [])]
    if any("@" not in r["agent"] for r in rows) and capacity.check()["busy"]:
        rows = [r for r in rows if "@" in r["agent"]]
    if not rows:
        return None
    avoid = avoid or set()
    return min(rows, key=lambda r: (r["agent"].partition("@")[0] in avoid, r["runs_last_5h"]))["agent"]


def _host(name: str) -> Dict[str, Any]:
    for host in config_manager.get("fleet_hosts") or []:
        if host["name"] == name:
            return host
    raise ValueError(f"Unknown host '{name}'. Add it with: agent-comms fleet add-host")


def _quote_ps(arg: str) -> str:
    return "'" + arg.replace("'", "''") + "'"


def _same_folder(cwd: str) -> str:
    try:
        return "~/" + Path(cwd).resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return "~"


def build_command(slot: str, prompt: str, cwd: str, capsule_id: Optional[str] = None) -> List[str]:
    agent, _, host_name = slot.partition("@")
    full = config_manager.get("fleet_permissions") == "full" or agent in (config_manager.get("fleet_full_agents") or [])
    mode = "full" if full else "auto"
    model = config_manager.get("ollama_model") or "gpt-oss:120b-cloud"
    cmd = [part.format(prompt=prompt, model=model) for part in COMMANDS[agent][mode]]
    if not host_name:
        return cmd
    host = _host(host_name)
    spec = remote.encode({
        "cmd": cmd,
        "folder": host.get("dir") or _same_folder(cwd),
        "capsule": capsule_id,
        "timeout": int(config_manager.get("fleet_timeout") or 1800),
    })
    if host.get("shell") == "powershell":
        remote_cmd = f"agent-comms remote-run {spec}"
    else:
        script = f'export PATH="$PATH:{PATH_DIRS}"; agent-comms remote-run {spec}'
        remote_cmd = f'exec "${{SHELL:-sh}}" -lc {shlex.quote(script)}'
    return ["ssh", "-n", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR", host["ssh"], remote_cmd]


def submit(
    prompts: List[str],
    cwd: Optional[str] = None,
    agent: Optional[str] = None,
    caller: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Starts one background job per prompt, each on a different provider when possible."""
    cwd = str(Path(cwd or Path.cwd()).resolve())
    jobs = []
    used = {caller} if caller else set()
    for prompt in prompts:
        slot = agent or pick(avoid=used)
        if not slot:
            raise RuntimeError("No agent CLIs are available right now (none installed, or all resting).")
        job = {
            "id": uuid.uuid4().hex[:8],
            "prompt": prompt,
            "agent": slot,
            "cwd": cwd,
            "status": "queued",
            "tried": [],
            "created": time.time(),
            "caller": caller,
        }
        used.add(slot.partition("@")[0])
        _record_run(slot)
        write_job(job)
        subprocess.Popen(
            [sys.executable, "-m", "agent_comms.cli", "jobs", "--work", job["id"]],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        jobs.append(job)
    return jobs


def write_job(job: Dict[str, Any]):
    (_data_dir() / f"{job['id']}.json").write_text(json.dumps(job, indent=2), encoding="utf-8")


def read_job(job_id: str) -> Optional[Dict[str, Any]]:
    path = _data_dir() / f"{job_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    paths = sorted(_data_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths[:limit]]


def _share_state(job: Dict[str, Any]) -> Optional[str]:
    """Uploads the project's current state so a helper on another machine starts from it."""
    from agent_comms.capsule.packager import CapsulePackager
    from agent_comms.capsule.store import CapsuleStore

    packager = CapsulePackager(workspace_path=Path(job["cwd"]))
    if not packager.git.is_git_repo():
        return None
    capsule = packager.package(
        task_id=f"job-{job['id']}",
        title=f"Helper job {job['id']}",
        executive_summary="Project state for a helper job.",
        goal=job["prompt"][:500],
        agent_name="agent-comms-fleet",
    )
    store = CapsuleStore()
    store.save(capsule, push_remote=False)
    store.push_to_storage(capsule)
    return capsule.capsule_id


def _take_patch(job: Dict[str, Any], output: str) -> str:
    """Pulls the helper's patch out of the output and applies it to the local project."""
    if remote.PATCH_START not in output:
        return output
    before, _, rest = output.partition(remote.PATCH_START)
    patch, _, after = rest.partition(remote.PATCH_END)
    patch = patch.lstrip("\n")
    patch_file = _data_dir() / f"{job['id']}.patch"
    patch_file.write_text(patch, encoding="utf-8")
    res = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch_file)], cwd=job["cwd"], capture_output=True, text=True)
    if res.returncode != 0:
        res = subprocess.run(["git", "apply", "--3way", "--whitespace=nowarn", str(patch_file)], cwd=job["cwd"], capture_output=True, text=True)
    note = (
        "(file changes from the helper were applied to this project)"
        if res.returncode == 0
        else f"(could not apply the helper's changes automatically; patch saved at {patch_file}: {res.stderr.strip()[:300]})"
    )
    return f"{before.rstrip()}\n{after.strip()}\n{note}".strip()


def work(job_id: str):
    """Runs a job, moving to another agent if one hits its usage limit or fails to start."""
    job = read_job(job_id)
    timeout = int(config_manager.get("fleet_timeout") or 1800)
    prompt = WORKER_PREFIX.format(cwd=job["cwd"], prompt=job["prompt"])
    slot = job["agent"]

    while slot and slot not in job["tried"]:
        job.update(agent=slot, status="running", started=time.time())
        job["tried"].append(slot)
        write_job(job)
        capsule_id = None
        if "@" in slot and not job.get("capsule_failed"):
            try:
                capsule_id = job.get("capsule_id") or _share_state(job)
                job["capsule_id"] = capsule_id
            except Exception as e:
                job["capsule_failed"] = str(e)
        try:
            with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
                code = subprocess.run(
                    build_command(slot, prompt, job["cwd"], capsule_id),
                    cwd=job["cwd"],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    stdin=subprocess.DEVNULL,
                ).returncode
                out.seek(0)
                output = out.read().strip()
        except subprocess.TimeoutExpired:
            output, code = f"Stopped after {timeout} seconds.", -1
        except Exception as e:
            output, code = str(e), -1

        if "@" in slot:
            output = _take_patch(job, output)
        job.update(output=output[-MAX_OUTPUT:], exit_code=code, finished=time.time())
        broken = hit_limit(output[-2000:]) or code not in (0, -1)
        if not broken:
            break
        if code == BUSY_EXIT:
            host = slot.partition("@")[2]
            for other in available_slots():
                if other.partition("@")[2] == host:
                    _cool_down(other, BUSY_SECONDS)
        else:
            _cool_down(slot)
        slot = pick(exclude=job["tried"], avoid={job.get("caller")})
        if slot:
            _record_run(slot)

    job["status"] = "done" if job.get("exit_code") == 0 else "failed"
    write_job(job)


def wait(job_ids: List[str], timeout: float = 1800) -> List[Dict[str, Any]]:
    end = time.time() + timeout
    while True:
        jobs = [read_job(j) for j in job_ids]
        if all(j and j["status"] in ("done", "failed") for j in jobs) or time.time() > end:
            return jobs
        time.sleep(2)
