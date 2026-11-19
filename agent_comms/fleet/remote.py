"""
Remote Job Side
===============
Runs a helper job sent over SSH. The sender's project state arrives as a capsule;
the helper works in a throwaway git worktree, and only the helper's own changes
are sent back as a patch. The machine's real project folder is never touched.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.fleet import capacity

PATCH_START = "<<<AGENT-COMMS-PATCH>>>"
PATCH_END = "<<<AGENT-COMMS-PATCH-END>>>"
BUSY_EXIT = 75


def encode(spec: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")


def _git(folder: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=agent-comms", "-c", "user.email=agent-comms@localhost", "-C", str(folder), *args],
        capture_output=True, text=True, check=check,
    )


def _run(cmd: list, cwd: Path, timeout: int) -> tuple[str, int]:
    cmd = [shutil.which(cmd[0]) or cmd[0], *cmd[1:]]
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        try:
            code = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, timeout=timeout).returncode
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


def run(encoded: str) -> int:
    spec = json.loads(base64.b64decode(encoded).decode("utf-8"))
    state = capacity.check()
    if state["busy"]:
        print(f"BUSY: {state['reason']}")
        return BUSY_EXIT

    folder = Path(spec.get("folder") or "~").expanduser()
    if not folder.is_dir():
        folder = Path.home()
    tree = _worktree(folder, spec.get("capsule"))
    output, code = _run(spec["cmd"], tree or folder, int(spec.get("timeout") or 1800))
    print(output)

    if tree:
        _git(tree, "add", "-A")
        patch = _git(tree, "diff", "--cached", "--binary", "HEAD").stdout
        if patch.strip():
            print(PATCH_START)
            print(patch, end="" if patch.endswith("\n") else "\n")
            print(PATCH_END)
        _git(folder, "worktree", "remove", "--force", str(tree))
    else:
        print("(note: worked in this machine's own copy of the project, so file changes stayed here)")
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
