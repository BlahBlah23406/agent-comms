"""
Fleet Runner
============
Hands tasks to the agent CLIs installed on this machine (and on SSH hosts),
spreading the work so no single subscription runs out first.
"""

from __future__ import annotations

import json
import os
import platform
import re
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
        "auto": ["codex", "exec", "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
                 "--skip-git-repo-check", "{prompt}"],
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
FAILED_SECONDS = 600
BROKEN_SECONDS = 6 * 3600
UNREACHABLE_SECONDS = 300
BUSY_SECONDS = 600
SSH_FAILED = 255
BUSY_EXIT = remote.BUSY_EXIT
PATH_DIRS = "$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"
EXTRA_DIRS = [str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin"]
MAX_OUTPUT = 20000

# The agent started but can't work at all on that machine (exit code is often still 0).
BROKEN_PATTERNS = {
    "its sandbox can't start there": re.compile(r"bwrap: |Failed to create unified exec process|sandbox (?:setup|initiali[sz]ation) failed", re.I),
    "it isn't logged in there": re.compile(r"Waiting for authentication|authentication (?:timed out|failed)|Please run /login|not logged in|Invalid API key", re.I),
}

FOLDER_TOKEN = "@@AGENT_COMMS_FOLDER@@"
WORKER_PREFIX = (
    "You are a helper agent. Your project folder is {folder} (the current folder). Read and edit files only "
    "inside it, even if you know another copy of this project elsewhere. Do only the task below, then stop. "
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
    return _caller_from_parents()


def _caller_from_parents() -> Optional[str]:
    """Walks up the process tree; MCP clients don't always say who they are."""
    if platform.system() == "Windows":
        return None
    pid = os.getppid()
    for _ in range(8):
        try:
            out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        if not out:
            return None
        ppid, _, comm = out.partition(" ")
        name = os.path.basename(comm.strip()).lower()
        for agent in ("claude", "codex", "agy"):
            if name == agent:
                return agent
        if not ppid.strip().isdigit() or int(ppid) <= 1:
            return None
        pid = int(ppid)
    return None


def _which(name: str) -> Optional[str]:
    """Finds a CLI even when the app that started us passed a short PATH."""
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(EXTRA_DIRS))


def _ssh_env() -> Dict[str, str]:
    """Codex starts MCP servers without SSH_AUTH_SOCK, so a key with a passphrase can't be used.
    On macOS the login agent's socket can be read back from launchd."""
    env = dict(os.environ)
    if not env.get("SSH_AUTH_SOCK") and platform.system() == "Darwin":
        try:
            sock = subprocess.run(["launchctl", "getenv", "SSH_AUTH_SOCK"],
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sock = ""
        if sock:
            env["SSH_AUTH_SOCK"] = sock
    return env


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


def _write_atomic(path: Path, text: str):
    """Several helper jobs write at once; a reader must never see half a file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class _Lock:
    """A lock file shared by every process that changes the usage file."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        end = time.time() + 10
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def save_usage(usage: Dict[str, Any]):
    _write_atomic(_usage_file(), json.dumps(usage, indent=2))


def _change_usage(change):
    with _Lock(_usage_file().with_suffix(".lock")):
        usage = load_usage()
        usage.setdefault("runs", {})
        usage.setdefault("cooldown", {})
        change(usage)
        save_usage(usage)


def _record_run(slot: str):
    def change(usage):
        now = time.time()
        runs = [t for t in usage["runs"].get(slot, []) if now - t < WINDOW_SECONDS]
        usage["runs"][slot] = runs + [now]
    _change_usage(change)


def _cool_down(slot: str, seconds: int = COOLDOWN_SECONDS, reason: Optional[str] = None):
    def change(usage):
        until = time.time() + seconds
        if until < usage["cooldown"].get(slot, 0):
            return
        usage["cooldown"][slot] = until
        if reason:
            usage.setdefault("reason", {})[slot] = reason
        else:
            usage.get("reason", {}).pop(slot, None)
    _change_usage(change)


def broken_reason(output: str) -> Optional[str]:
    for reason, pattern in BROKEN_PATTERNS.items():
        if pattern.search(output):
            return reason
    return None


def available_slots() -> List[str]:
    """Every agent we can use, written as 'agent' or 'agent@host'."""
    names = config_manager.get("fleet_agents") or DEFAULT_AGENTS
    slots = [n for n in names if n in COMMANDS and _which(n)]
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
        row = {
            "agent": slot,
            "runs_last_5h": len(runs),
            "resting_until": time.strftime("%H:%M", time.localtime(cool)) if cool > now else None,
        }
        if cool > now and usage.get("reason", {}).get(slot):
            row["why"] = usage["reason"][slot]
        rows.append(row)
    return rows


def pick(exclude: Optional[List[str]] = None, avoid: Optional[set] = None) -> Optional[str]:
    """Least-used free slot, trying providers in `avoid` (e.g. the caller's own) last."""
    rows = [r for r in status() if not r["resting_until"] and r["agent"] not in (exclude or [])]
    if any("@" not in r["agent"] for r in rows) and capacity.check()["busy"]:
        rows = [r for r in rows if "@" in r["agent"]]
    if not rows:
        return None
    avoid = avoid or set()
    # One subscription covers a provider on every machine, so spread by provider first.
    by_provider: Dict[str, int] = {}
    for r in status():
        provider = r["agent"].partition("@")[0]
        by_provider[provider] = by_provider.get(provider, 0) + r["runs_last_5h"]

    def rank(r):
        provider = r["agent"].partition("@")[0]
        return (provider in avoid, by_provider[provider], r["runs_last_5h"])
    return min(rows, key=rank)["agent"]


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


def build_command(slot: str, prompt: str, cwd: str, capsule_id: Optional[str] = None, snapshot: bool = False) -> List[str]:
    agent, _, host_name = slot.partition("@")
    host = _host(host_name) if host_name else {}
    full = (
        config_manager.get("fleet_permissions") == "full"
        or agent in (config_manager.get("fleet_full_agents") or [])
        or agent in host.get("full_agents", [])
    )
    mode = "full" if full else "auto"
    model = config_manager.get("ollama_model") or "gpt-oss:120b-cloud"
    cmd = [part.format(prompt=prompt, model=model) for part in COMMANDS[agent][mode]]
    if not host_name:
        return [_which(cmd[0]) or cmd[0], *cmd[1:]]
    spec = remote.encode({
        "cmd": cmd,
        "folder": host.get("dir") or _same_folder(cwd),
        "capsule": capsule_id,
        "snapshot": snapshot,
        "timeout": int(config_manager.get("fleet_timeout") or 1800),
    })
    if host.get("shell") == "powershell":
        remote_cmd = f"agent-comms remote-run {spec}"
    else:
        script = f'export PATH="$PATH:{PATH_DIRS}"; agent-comms remote-run {spec}'
        remote_cmd = f'exec "${{SHELL:-sh}}" -lc {shlex.quote(script)}'
    return ["ssh", *([] if snapshot else ["-n"]), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "LogLevel=ERROR", host["ssh"], remote_cmd]


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
    note = None
    if agent and caller and agent.partition("@")[0] == caller:
        other = pick(avoid=used)
        if other and other.partition("@")[0] != caller:
            # Asking for your own provider would spend the subscription we are trying to spare.
            note = f"'{agent}' is your own provider, so other providers go first; it is still used if they fail."
            agent = None
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
            "attempts": [],
        }
        if note:
            job["note"] = note
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
    _write_atomic(_data_dir() / f"{job['id']}.json", json.dumps(job, indent=2))


def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    if platform.system() == "Windows":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return True
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _check_stale(job: Dict[str, Any]) -> Dict[str, Any]:
    """A job whose worker died (reboot, crash, killed) would otherwise say 'running' forever."""
    if job.get("status") == "queued" and time.time() - job.get("created", 0) > 120:
        dead = True
    elif job.get("status") == "running" and job.get("pid"):
        dead = not _alive(job["pid"])
    elif job.get("status") == "running":
        dead = time.time() - job.get("started", job.get("created", 0)) > int(config_manager.get("fleet_timeout") or 1800) + 300
    else:
        dead = False
    if dead:
        job.update(status="failed", exit_code=-1, finished=time.time(),
                   output=(job.get("output") or "") + "\n(the helper process stopped before finishing; run the task again)")
        write_job(job)
    return job


def read_job(job_id: str) -> Optional[Dict[str, Any]]:
    path = _data_dir() / f"{job_id}.json"
    return _check_stale(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def running_local_jobs() -> int:
    """Helper jobs this machine is running itself (not ones it handed to other machines)."""
    count = 0
    for path in _data_dir().glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if job.get("status") == "running" and "@" not in job.get("agent", "") and _alive(job.get("pid")):
            count += 1
    return count


def running_incoming_jobs() -> int:
    """Jobs other machines sent here; remote-run leaves an incoming-<pid> marker while it works."""
    count = 0
    for marker in _data_dir().glob("incoming-*.pid"):
        try:
            pid = int(marker.stem.partition("-")[2])
        except ValueError:
            continue
        if _alive(pid):
            count += 1
        else:
            marker.unlink(missing_ok=True)
    return count


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    paths = sorted(_data_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_check_stale(json.loads(p.read_text(encoding="utf-8"))) for p in paths[:limit]]


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


def _take_patch(job: Dict[str, Any], output: str, apply: bool = True) -> str:
    """Pulls the helper's patch out of the output and applies it to the local project."""
    if remote.PATCH_START not in output:
        return output
    before, _, rest = output.partition(remote.PATCH_START)
    patch, _, after = rest.partition(remote.PATCH_END)
    patch = patch.lstrip("\n")
    patch_file = _data_dir() / f"{job['id']}.patch"
    patch_file.write_text(patch, encoding="utf-8")
    if not apply:
        return f"{before.rstrip()}\n{after.strip()}\n(this attempt failed, so its changes were not applied; patch saved at {patch_file})".strip()
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
    template = WORKER_PREFIX.format(folder=FOLDER_TOKEN, prompt=job["prompt"])
    slot = job["agent"]

    job.setdefault("attempts", [])
    while slot and slot not in job["tried"]:
        job.update(agent=slot, status="running", started=time.time(), pid=os.getpid())
        # A remote machine fills in its own throwaway folder.
        prompt = template if "@" in slot else template.replace(FOLDER_TOKEN, job["cwd"])
        job["tried"].append(slot)
        write_job(job)
        capsule_id = None
        snap = None
        if "@" in slot:
            if not job.get("capsule_failed"):
                try:
                    capsule_id = job.get("capsule_id") or _share_state(job)
                    job["capsule_id"] = capsule_id
                except Exception as e:
                    job["capsule_failed"] = str(e)
            snap = remote.snapshot(Path(job["cwd"]))
        try:
            with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
                code = subprocess.run(
                    build_command(slot, prompt, job["cwd"], capsule_id, snapshot=bool(snap)),
                    cwd=job["cwd"],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    input=snap,
                    stdin=None if snap else subprocess.DEVNULL,
                    text=bool(snap) or None,
                    env=_ssh_env() if "@" in slot else None,
                ).returncode
                out.seek(0)
                output = out.read().strip()
        except subprocess.TimeoutExpired:
            output, code = f"Stopped after {timeout} seconds.", -1
        except Exception as e:
            output, code = str(e), -1

        limited = hit_limit(output[-2000:])
        broken = broken_reason(output[-6000:])
        accepted = not limited and not broken and code in (0, -1)
        if "@" in slot:
            # Only the attempt we keep may change the project; the next agent redoes a failed one.
            output = _take_patch(job, output, apply=accepted)
        job.update(output=output[-MAX_OUTPUT:], exit_code=code, finished=time.time())
        if accepted:
            break
        if broken and code == 0:
            job["exit_code"] = code = 1
        job["attempts"].append({"agent": slot, "exit_code": code, "error": output[-400:]})
        host = slot.partition("@")[2]
        if host and code in (BUSY_EXIT, SSH_FAILED):
            # The machine, not the agent, is the problem: rest the whole machine briefly.
            for other in available_slots():
                if other.partition("@")[2] == host:
                    _cool_down(other, BUSY_SECONDS if code == BUSY_EXIT else UNREACHABLE_SECONDS)
                    if other not in job["tried"]:
                        job["tried"].append(other)
        elif broken:
            _cool_down(slot, BROKEN_SECONDS, reason=broken)
        else:
            _cool_down(slot, COOLDOWN_SECONDS if limited else FAILED_SECONDS)
        write_job(job)
        slot = pick(exclude=job["tried"], avoid={job.get("caller")})
        if slot:
            _record_run(slot)

    job["status"] = "done" if job.get("exit_code") == 0 else "failed"
    if job["status"] == "failed" and job["attempts"]:
        tried = "; ".join(f"{a['agent']} (exit {a['exit_code']}): {a['error'].strip().splitlines()[-1][:150] if a['error'].strip() else 'no output'}"
                          for a in job["attempts"])
        job["output"] = f"{job.get('output', '')}\n\nEvery agent tried failed: {tried}"
    write_job(job)


def wait(job_ids: List[str], timeout: float = 1800) -> List[Dict[str, Any]]:
    end = time.time() + min(timeout, 900)
    while True:
        jobs = [read_job(j) for j in job_ids]
        if all(j and j["status"] in ("done", "failed") for j in jobs) or time.time() > end:
            return jobs
        time.sleep(2)


def mcp_run(arguments: Dict[str, Any], folder: str, client_name: str = "") -> str:
    """The run_on_agents tool. Lives here so a code update reaches chats that are already open."""
    try:
        jobs = submit(arguments["tasks"], cwd=folder, agent=arguments.get("agent"), caller=detect_caller(client_name))
    except Exception as e:
        return json.dumps({"error": str(e), "what_to_do": "Tell the user no helper could take the work, then do it yourself."})
    rows = [{"job_id": j["id"], "agent": j["agent"], "task": j["prompt"][:200]} for j in jobs]
    notes = sorted({j["note"] for j in jobs if j.get("note")})
    return json.dumps({
        "jobs": rows,
        "notes": notes,
        "next": "Do your own part now. Then call check_jobs with these job_ids (wait_seconds up to 600). "
                "If a job failed, read its attempts and tell the user why before doing that part yourself.",
    }, indent=2)


def mcp_check(job_ids: List[str], wait_seconds: float = 0) -> str:
    jobs = wait(job_ids, wait_seconds or 0)
    return json.dumps([
        {
            "id": j["id"], "agent": j["agent"], "status": j["status"], "exit_code": j.get("exit_code"),
            "attempts": [f"{a['agent']} exit {a['exit_code']}: {a['error'].strip()[-200:]}" for a in j.get("attempts", [])],
            "output": j.get("output"),
        } if j else None
        for j in jobs
    ], indent=2)
