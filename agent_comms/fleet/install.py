"""
Plugin Installer
================
Adds agent-comms to Claude Code, Codex, and Antigravity (agy):
the autosave hook, the MCP server, and a short instructions block.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

START = "<!-- agent-comms:start -->"
END = "<!-- agent-comms:end -->"

GUIDANCE = """{start}
## agent-comms (always on)

This machine is `{alias}`. Other machines: {peers}.

1. **Saving work:** a hook saves a capsule of this chat every other turn and right away when a usage limit
   shows up. You don't need to do anything. If the user says "continue" or "pick up where I left off",
   call the `resume_latest` tool (or run `agent-comms resume`) and keep going from that briefing.
2. **Sharing the work:** the user wants work spread across subscriptions. If a task has two or more parts
   that touch different files (or research that needs no files), hand out every part but one with the
   `run_on_agents` tool, keep one part for yourself, and do it while they run. Leave `agent` empty: it
   picks the least-used provider and uses your own provider last. Then read results with `check_jobs`
   (wait_seconds up to 600). Small one-part tasks: just do them. If the user says not to use other agents, don't.
3. If a helper job fails, read its `attempts`, tell the user why in one line, then do that part yourself.
   Read every helper's result before you tell the user it is done.
{end}
"""

APP_GUIDANCE = """You are connected to the agent-comms tools. Follow these rules without being asked:
1. After every second reply, call save_progress with a short project name, the goal, what is done,
   and the next step. Use the same project name every time (the code folder name if there is one).
2. If I say "continue" or "pick up where I left off", call resume_latest with the project name
   and keep going from that briefing.
3. If a task is big and is about code on my computer, split it into parts and hand them out with
   run_on_agents (set folder to the project folder), then read the results with check_jobs.
   Don't do this if I say not to.
"""


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_block(path: Path, text: str):
    """Puts our block in a Markdown file, replacing an old copy, keeping everything else."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n?", re.S)
    if pattern.search(old):
        new = pattern.sub(lambda _: text, old)
    else:
        new = (old.rstrip() + "\n\n" if old.strip() else "") + text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")


def _set_hook(hooks: Dict[str, Any], event: str, command: str, timeout: int = 30, matcher: str = ""):
    keep = [
        h for h in hooks.get(event, [])
        if "agent_comms" not in json.dumps(h) and "agent-comms" not in json.dumps(h)
    ]
    group: Dict[str, Any] = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    if matcher:
        group = {"matcher": matcher, **group}
    hooks[event] = keep + [group]


def _drop_hooks(hooks: Dict[str, Any], event: str):
    keep = [h for h in hooks.get(event, []) if "agent_comms" not in json.dumps(h)]
    if keep:
        hooks[event] = keep
    else:
        hooks.pop(event, None)


def hook_command(python: str, agent: str) -> str:
    return f'"{python}" -m agent_comms.cli autosave --agent {agent}'


def tick_command(python: str, agent: str) -> str:
    return f'"{python}" "{Path(__file__).with_name("tick.py")}" {agent}'


def install_claude(home: Path, python: str):
    path = home / ".claude" / "settings.json"
    data = _read_json(path)
    hooks = data.setdefault("hooks", {})
    _drop_hooks(hooks, "PreToolUse")
    _set_hook(hooks, "Stop", hook_command(python, "claude"))
    _set_hook(hooks, "PostToolUse", tick_command(python, "claude"), matcher="*")
    _write_json(path, data)
    return path


def install_codex(home: Path, python: str, alias: str):
    hooks_path = home / ".codex" / "hooks.json"
    data = _read_json(hooks_path)
    _set_hook(data.setdefault("hooks", {}), "Stop", hook_command(python, "codex"))
    _set_hook(data["hooks"], "PostToolUse", tick_command(python, "codex"), matcher="*")
    _write_json(hooks_path, data)

    config = home / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    if "[mcp_servers.agent-comms]" not in text:
        py = python.replace("\\", "\\\\")
        text += (
            f'\n[mcp_servers.agent-comms]\ncommand = "{py}"\nargs = ["-m", "agent_comms.cli", "mcp"]\n'
            f'\n[mcp_servers.agent-comms.env]\nAGENT_COMMS_MACHINE_ALIAS = "{alias}"\n'
        )
    text = codex_server_options(text)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text, encoding="utf-8")
    return hooks_path


CODEX_OPTIONS = [
    # Codex gives MCP servers only a few env vars; without the SSH agent a key with a passphrase fails.
    'env_vars = ["SSH_AUTH_SOCK"]',
    # check_jobs can wait up to 10 minutes; Codex's default tool timeout is 60 seconds.
    "tool_timeout_sec = 900",
]


def codex_server_options(text: str) -> str:
    """Adds our options under [mcp_servers.agent-comms] if they are missing, keeping the rest."""
    header = "[mcp_servers.agent-comms]\n"
    at = text.find(header)
    if at < 0:
        return text
    body_end = text.find("\n[", at + len(header))
    body = text[at + len(header): body_end if body_end >= 0 else len(text)]
    missing = [o for o in CODEX_OPTIONS if o.split(" =")[0] + " =" not in body]
    if not missing:
        return text
    insert = at + len(header)
    return text[:insert] + "".join(o + "\n" for o in missing) + text[insert:]


def install_agy(home: Path, python: str, alias: str):
    path = home / ".gemini" / "config" / "hooks.json"
    data = _read_json(path)
    data["agent-comms"] = {
        "Stop": [{"type": "command", "command": hook_command(python, "agy"), "timeout": 30}],
        "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": tick_command(python, "agy"), "timeout": 10}]}],
    }
    _write_json(path, data)
    subprocess.run(
        ["agy", "mcp", "add", "--env", f"AGENT_COMMS_MACHINE_ALIAS={alias}",
         "agent-comms", python, "-m", "agent_comms.cli", "mcp"],
        capture_output=True,
        check=False,
    )
    return path


def install_all(home: Path, alias: str, peers: List[str], python: str = sys.executable) -> List[str]:
    """Installs into every agent found in this home folder. Returns what it did."""
    done: List[str] = []
    guidance = GUIDANCE.format(start=START, end=END, alias=alias, peers=", ".join(peers) or "none yet")

    steps: List[tuple[str, Path, Callable[[], Any]]] = [
        ("Claude Code", home / ".claude", lambda: install_claude(home, python)),
        ("Codex", home / ".codex", lambda: install_codex(home, python, alias)),
        ("Antigravity (agy)", home / ".gemini" / "antigravity-cli", lambda: install_agy(home, python, alias)),
    ]
    for name, folder, step in steps:
        if not folder.exists():
            continue
        try:
            step()
            done.append(f"{name}: autosave hook + MCP")
        except Exception as e:
            done.append(f"{name}: failed ({e})")

    for name, md in [
        ("Claude Code", home / ".claude" / "CLAUDE.md"),
        ("Codex", home / ".codex" / "AGENTS.md"),
        ("Antigravity (agy)", home / ".gemini" / "GEMINI.md"),
    ]:
        if md.parent.exists():
            write_block(md, guidance)
            done.append(f"{name}: instructions in {md}")

    return done
