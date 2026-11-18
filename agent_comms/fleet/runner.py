"""
Fleet Runner
============
Hands tasks to the agent CLIs installed on this machine (and on SSH hosts),
spreading the work so no single subscription runs out first.
"""

from __future__ import annotations

import json
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
from agent_comms.fleet.autosave import hit_limit

COMMANDS = {
    "claude": {
        "edits": ["claude", "-p", "--permission-mode", "acceptEdits", "{prompt}"],
        "full": ["claude", "-p", "--dangerously-skip-permissions", "{prompt}"],
    },
    "codex": {
        "edits": ["codex", "exec", "-s", "workspace-write", "--skip-git-repo-check", "{prompt}"],
        "full": ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "{prompt}"],
    },
    "gemini": {
        "edits": ["gemini", "--approval-mode", "auto_edit", "-p", "{prompt}"],
        "full": ["gemini", "--yolo", "-p", "{prompt}"],
    },
    "agy": {
        "edits": ["agy", "--mode", "accept-edits", "-p", "{prompt}"],
        "full": ["agy", "--dangerously-skip-permissions", "-p", "{prompt}"],
    },
    "ollama": {
        "edits": ["ollama", "run", "{model}", "{prompt}"],
        "full": ["ollama", "run", "{model}", "{prompt}"],
    },
}
DEFAULT_AGENTS = ["claude", "codex", "agy"]
WINDOW_SECONDS = 5 * 3600
COOLDOWN_SECONDS = 3600
BUSY_SECONDS = 600
BUSY_EXIT = 75
PATH_DIRS = "$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"
MAX_OUTPUT = 20000

WORKER_PREFIX = (
    "You are a helper agent working in {cwd}. Do only the task below, then stop. "
    "Other helpers may be editing other files at the same time, so only touch what this task needs. "
    "End with a short summary of what you changed.\n\nTask: {prompt}"
)


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


def pick(exclude: Optional[List[str]] = None) -> Optional[str]:
    rows = [r for r in status() if not r["resting_until"] and r["agent"] not in (exclude or [])]
    if any("@" not in r["agent"] for r in rows) and capacity.check()["busy"]:
        rows = [r for r in rows if "@" in r["agent"]]
    if not rows:
        return None
    return min(rows, key=lambda r: r["runs_last_5h"])["agent"]


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


def build_command(slot: str, prompt: str, cwd: str) -> List[str]:
    agent, _, host_name = slot.partition("@")
    full = config_manager.get("fleet_permissions") == "full" or agent in (config_manager.get("fleet_full_agents") or [])
    mode = "full" if full else "edits"
    model = config_manager.get("ollama_model") or "gpt-oss:120b-cloud"
    cmd = [part.format(prompt=prompt, model=model) for part in COMMANDS[agent][mode]]
    if not host_name:
        return cmd
    host = _host(host_name)
    folder = host.get("dir") or _same_folder(cwd)
    if host.get("shell") == "powershell":
        remote = (
            f"agent-comms busy --gate; if ($LASTEXITCODE -eq {BUSY_EXIT}) {{ exit {BUSY_EXIT} }}; "
            f"cd {_quote_ps(folder)} -ErrorAction SilentlyContinue; & " + " ".join(_quote_ps(c) for c in cmd)
        )
    else:
        script = (
            f'export PATH="$PATH:{PATH_DIRS}"; agent-comms busy --gate; [ $? -eq {BUSY_EXIT} ] && exit {BUSY_EXIT}; '
            f"cd {folder} 2>/dev/null; {shlex.join(cmd)}"
        )
        remote = f'exec "${{SHELL:-sh}}" -lc {shlex.quote(script)}'
    return ["ssh", "-n", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR", host["ssh"], remote]


def submit(prompts: List[str], cwd: Optional[str] = None, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Starts one background job per prompt and returns the job records."""
    cwd = str(Path(cwd or Path.cwd()).resolve())
    jobs = []
    for prompt in prompts:
        slot = agent or pick()
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
            "fixed_agent": bool(agent),
        }
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
        try:
            with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
                code = subprocess.run(
                    build_command(slot, prompt, job["cwd"]),
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

        job.update(output=output[-MAX_OUTPUT:], exit_code=code, finished=time.time())
        broken = hit_limit(output[-2000:]) or code not in (0, -1)
        if not broken or job["fixed_agent"]:
            break
        _cool_down(slot, BUSY_SECONDS if code == BUSY_EXIT else COOLDOWN_SECONDS)
        slot = pick(exclude=job["tried"])
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
