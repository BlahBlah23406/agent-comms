"""
Tool-Call Tick
==============
Runs after every tool call. Kept to the standard library so it starts fast.
Every 10 minutes it starts a background save, so long turns are saved too.
It also saves right away when the chat is about to run out of usage: Codex
writes how much of its limit is used, and Claude Code warns before it cuts a
turn off. That save is the one a fresh agent resumes from.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EVERY_SECONDS = 600
NEAR_LIMIT_PERCENT = 90
TAIL_BYTES = 200_000

# Warnings that come before (or right at) the cut-off. Only a message that starts with one counts,
# so a chat or tool output that merely talks about limits doesn't trigger a save.
WARNINGS = re.compile(
    r'"(?:content|message|text)":\s*"[\[\s■⚠]*(?:(?:error|warning|heads up)[:,]?\s*)?(?:you(?:[\'’]ve| have)\s+)?'
    r'(grace allowance remains|usage limit (?:was )?reached|(?:hit|reached) your [^"]{0,20}limit'
    r'|approaching (?:your )?(?:usage|rate) limit|less than \d+% of your|RESOURCE_EXHAUSTED|quota exceeded)',
    re.I,
)
USED_PERCENT = re.compile(r'"used_percent":\s*([\d.]+)')


def near_limit(transcript, percent=NEAR_LIMIT_PERCENT):
    """Why this chat is about to run out of usage, or None."""
    if not transcript:
        return None
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            tail = f.read().decode("utf-8", "ignore")
    except OSError:
        return None
    lines = tail.splitlines()[-60:]
    # Codex: the newest rate-limit report says how much of the 5-hour and weekly limits is used.
    for line in reversed(lines):
        if '"rate_limits"' in line:
            used = [float(v) for v in USED_PERCENT.findall(line)]
            if used and max(used) >= percent:
                return f"{max(used):.0f}% of the usage limit used"
            break
    for line in lines[-25:]:
        match = WARNINGS.search(line)
        if match:
            return match.group(1)
    return None


def _start_save(agent, raw, folder):
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
    try:
        percent = float(json.loads((folder / "config.json").read_text(encoding="utf-8")).get("save_at_percent") or NEAR_LIMIT_PERCENT)
    except (OSError, ValueError, TypeError, AttributeError):
        percent = NEAR_LIMIT_PERCENT
    why = near_limit(payload.get("transcript_path") or payload.get("transcriptPath"), percent)
    limit_key = f"limit:{session}"
    if why and now - state.get(limit_key, 0) >= EVERY_SECONDS:
        # Save now, once per warning, even if a regular save just ran.
        state[limit_key] = now
        state[session] = now
        payload["near_limit"] = why
        raw = json.dumps(payload)
    elif now - state.get(session, 0) < EVERY_SECONDS:
        return
    else:
        state[session] = now
    folder.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(dict(list(state.items())[-400:])), encoding="utf-8")
    _start_save(agent, raw, folder)


if __name__ == "__main__":
    main()
