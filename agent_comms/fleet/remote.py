"""
Remote Job Side
===============
Runs a helper job sent over SSH. The sender's project state arrives as a capsule;
the helper works in a throwaway git worktree, and only the helper's own changes
are sent back as a patch. The machine's real project folder is never touched.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.config import config_manager
from agent_comms.fleet import capacity

PATCH_START = "<<<AGENT-COMMS-PATCH>>>"
PATCH_END = "<<<AGENT-COMMS-PATCH-END>>>"
BUSY_EXIT = 75
FOLDER_TOKEN = "@@AGENT_COMMS_FOLDER@@"


def encode(spec: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")


def _git(folder: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=agent-comms", "-c", "user.email=agent-comms@localhost", "-C", str(folder), *args],
        capture_output=True, text=True, check=check,
    )


def _run(cmd: list, cwd: Path, timeout: int) -> tuple[str, int]:
    cmd = [shutil.which(cmd[0]) or cmd[0], *cmd[1:]]
    env = {**os.environ, "AGENT_COMMS_HELPER": "1"}
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        try:
            code = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, timeout=timeout, env=env).returncode
        except subprocess.TimeoutExpired:
            code = -1
        out.seek(0)
        return out.read(), code


def _worktree(folder: Path, capsule_id: Optional[str]) -> Optional[Path]:
    """A throwaway copy of the project at the sender's state, or None if that isn't possible."""
    if not capsule_id or _git(folder, "rev-parse", "--git-dir").returncode != 0:
        return None
    capsule = CapsuleStore().load_by_id(capsule_id, fetch_remote=True)
    base = capsule and capsule.workspace.base_commit
    if not base:
        return None
    if _git(folder, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        _git(folder, "fetch", "-q", "--all")
        if _git(folder, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
            return None
    tree = Path(tempfile.mkdtemp(prefix="agent-comms-job-"))
    tree.rmdir()
    if _git(folder, "worktree", "add", "-q", "--detach", str(tree), base).returncode != 0:
        return None
    CapsuleUnpacker(workspace_path=tree).apply(capsule, apply_workspace=True)
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "--no-verify", "--allow-empty", "-m", "sender state")
    return tree


def snapshot(folder: Path, limit_mb: int = 50) -> Optional[str]:
    """The sender's project as it is right now (tracked and new files, not ignored ones), so a
    machine without its own copy of the project can still work on it and send changes back."""
    files = _git(folder, "ls-files", "-z", "-co", "--exclude-standard")
    if files.returncode != 0:
        return None
    buf = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in filter(None, files.stdout.split("\0")):
            path = folder / name
            if not path.is_file() or path.is_symlink():
                continue
            total += path.stat().st_size
            if total > limit_mb * 1024 * 1024:
                return None
            tar.add(path, arcname=name, recursive=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _snapshot_tree(data: str) -> Optional[Path]:
    tree = Path(tempfile.mkdtemp(prefix="agent-comms-job-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(data)), mode="r:gz") as tar:
            tar.extractall(tree, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(tree)
    except (tarfile.TarError, ValueError, OSError):
        shutil.rmtree(tree, ignore_errors=True)
        return None
    _git(tree, "init", "-q")
    _git(tree, "config", "core.autocrlf", "false")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "--no-verify", "--allow-empty", "-m", "sender state")
    return tree


def run(encoded: str) -> int:
    spec = json.loads(base64.b64decode(encoded).decode("utf-8"))
    if spec.get("snapshot"):
        spec["snapshot_data"] = sys.stdin.read().strip()
    from agent_comms.fleet.runner import _Lock
    jobs_dir = config_manager.config_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    marker = jobs_dir / f"incoming-{os.getpid()}.pid"
    # Check and register in one step: jobs that arrive together must see each other.
    with _Lock(jobs_dir / "admit.lock"):
        state = capacity.check()
        if state["busy"]:
            print(f"BUSY: {state['reason']}")
            return BUSY_EXIT
        marker.touch()
    try:
        return _run_here(spec)
    finally:
        marker.unlink(missing_ok=True)


def _run_here(spec: Dict[str, Any]) -> int:
    folder = Path(spec.get("folder") or "~").expanduser()
    if not folder.is_dir():
        folder = Path.home()
    tree = _worktree(folder, spec.get("capsule"))
    copied = False
    if not tree and spec.get("snapshot_data"):
        tree = _snapshot_tree(spec["snapshot_data"])
        copied = tree is not None
    workdir = tree or folder
    cmd = [part.replace(FOLDER_TOKEN, str(workdir)) for part in spec["cmd"]]
    before = _git(folder, "status", "--porcelain").stdout if tree else ""
    output, code = _run(cmd, workdir, int(spec.get("timeout") or 1800))
    print(output)
    if tree and not copied and _git(folder, "status", "--porcelain").stdout != before:
        print(f"(warning: the helper also changed this machine's own copy at {folder}; those changes were left there)")

    if tree:
        _git(tree, "add", "-A")
        patch = _git(tree, "diff", "--cached", "--binary", "HEAD").stdout
        if patch.strip():
            print(PATCH_START)
            print(patch, end="" if patch.endswith("\n") else "\n")
            print(PATCH_END)
        if copied:
            shutil.rmtree(tree, ignore_errors=True)
        else:
            _git(folder, "worktree", "remove", "--force", str(tree))
    else:
        print("(note: worked in this machine's own copy of the project, so file changes stayed here)")
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
