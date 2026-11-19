"""
Tool-Call Tick
==============
Runs after every tool call. Kept to the standard library so it starts fast.
Every 10 minutes it starts a background save, so long turns are saved too.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

EVERY_SECONDS = 600


def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else "claude"
    raw = sys.stdin.read()
    print("{}")
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        return
    session = str(payload.get("session_id") or payload.get("conversationId") or payload.get("cwd") or "")
    folder = Path.home() / ".agent-comms"
    state_file = folder / "saves.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = time.time()
    if now - state.get(session, 0) < EVERY_SECONDS:
        return
    state[session] = now
    folder.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(dict(list(state.items())[-200:])), encoding="utf-8")
    payload_file = folder / f"tick-{os.getpid()}.json"
    payload_file.write_text(raw, encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "agent_comms.cli", "autosave", "--agent", agent, "--force", "--payload", str(payload_file)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


if __name__ == "__main__":
    main()
