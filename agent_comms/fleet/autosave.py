"""
Turn Autosave
=============
Saves a capsule every few turns (and right away when a usage limit shows up)
so any agent on any machine can continue the work.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule
from agent_comms.quota.watchdog import RATE_LIMIT_PATTERNS

KEEP_LOCAL = 5
MAX_SESSIONS = 200
ROLES = {"gemini": "assistant", "model": "assistant", "USER_INPUT": "user", "PLANNER_RESPONSE": "assistant"}


def task_id_for(folder: Path) -> str:
    return "auto-" + (re.sub(r"[^A-Za-z0-9_-]+", "-", folder.name).strip("-") or "root")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type", "text") in ("text", "input_text", "output_text")
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _message(obj: Any) -> Optional[Tuple[str, str]]:
    if not isinstance(obj, dict):
        return None
    msg = obj.get("payload") or obj.get("message") or obj
    if not isinstance(msg, dict):
        return None
    role = msg.get("role") or obj.get("type")
    role = ROLES.get(role, role)
    if role not in ("user", "assistant"):
        return None
    text = _text(msg.get("content"))
    request = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, re.S)
    text = (request.group(1) if request else text).strip()
    if not text or text.startswith("<"):
        return None
    return role, text


def read_transcript(path: Optional[str]) -> Tuple[List[Tuple[str, str]], str]:
    """Returns (messages, raw tail) from a Claude, Codex, or Gemini transcript."""
    if not path or not Path(path).is_file():
        return [], ""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    try:
        whole = json.loads(raw)
        rows = whole.get("messages", []) if isinstance(whole, dict) else whole
    except ValueError:
        rows = []
        for line in raw.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    messages = [m for m in (_message(r) for r in rows) if m]
    tail = "\n".join(raw.splitlines()[-3:])
    return messages, tail


def hit_limit(text: str) -> bool:
    return any(p.search(text) for p in RATE_LIMIT_PATTERNS)


def _count_turn(session_id: str) -> int:
    state_file = config_manager.config_dir / "turns.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state[session_id] = state.pop(session_id, 0) + 1
    state = dict(list(state.items())[-MAX_SESSIONS:])
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state[session_id]


def _prune(store: CapsuleStore, task_id: str):
    old = sorted(store.base_dir.glob(f"{task_id}_capsule-*.json"), key=lambda p: p.stat().st_mtime)
    for path in old[:-KEEP_LOCAL]:
        path.unlink(missing_ok=True)
        path.with_suffix(".md").unlink(missing_ok=True)


def autosave(
    payload: Dict[str, Any],
    agent: str,
    every: Optional[int] = None,
    store: Optional[CapsuleStore] = None,
) -> Optional[ContextCapsule]:
    folder = Path(payload.get("cwd") or Path.cwd()).resolve()
    session_id = str(payload.get("session_id") or payload.get("conversationId") or folder)
    turn = _count_turn(session_id)

    messages, tail = read_transcript(payload.get("transcript_path") or payload.get("transcriptPath"))
    reply = payload.get("last_assistant_message") or payload.get("prompt_response") or ""
    limited = hit_limit(f"{reply}\n{tail}")
    every = every or int(config_manager.get("autosave_every") or 2)
    if turn % every and not limited:
        return None

    users = [t for r, t in messages if r == "user"]
    if not reply:
        reply = next((t for r, t in reversed(messages) if r == "assistant"), "")
    first = users[0] if users else "Unknown goal"
    last = payload.get("prompt") or payload.get("lastUserInput") or (users[-1] if users else first)

    capsule = CapsulePackager(workspace_path=folder).package(
        task_id=task_id_for(folder),
        title=f"{folder.name}: {first[:80]}",
        executive_summary=reply[:2000] or "No reply yet.",
        goal=first[:1500],
        next_action=f"Continue from the last request: {last[:800]}",
        agent_name=agent,
        session_id=session_id,
        capture_loose_files=False,
    )
    capsule.extra_metadata.update({"autosave": True, "turn": turn, "hit_limit": limited})

    store = store or CapsuleStore()
    store.save(capsule)
    _prune(store, capsule.task_id)
    return capsule


def latest(task_id: str, store: Optional[CapsuleStore] = None) -> Optional[ContextCapsule]:
    store = store or CapsuleStore()
    best: Optional[ContextCapsule] = None
    for path in store.base_dir.glob(f"{task_id}_*.json"):
        try:
            cap = store.load_from_file(path)
        except Exception:
            continue
        if not best or cap.created_at > best.created_at:
            best = cap
    if store.storage_url:
        try:
            records = [r for r in store.list_storage_capsules(task_id=task_id) if r.task_id == task_id]
            newest = max(records, key=lambda r: r.created_at, default=None)
            if newest and (not best or newest.created_at > best.created_at):
                best = store.pull_from_storage(newest.capsule_id, save_local=True)
        except Exception:
            pass
    return best
