"""
Plugin Installer
================
Adds agent-comms to Claude Code, Codex, Gemini CLI, and Antigravity:
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
2. **Sharing the work:** before a big task, decide if it splits into parts that don't touch the same files.
   If it does, hand the parts out with the `run_on_agents` tool (or `agent-comms run "part 1" "part 2"`),
   keep one part for yourself, then check results with `check_jobs`. It picks whichever of
   claude / codex / gemini / agy (and SSH hosts) has been used the least and skips any that hit a limit.
   Small tasks: just do them. If the user says not to use other agents, don't.
3. Read every helper's result before you tell the user it is done.
{end}
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


def _set_hook(hooks: Dict[str, Any], event: str, command: str, timeout: int = 30):
    keep = [
        h for h in hooks.get(event, [])
        if "agent_comms" not in json.dumps(h) and "agent-comms" not in json.dumps(h)
    ]
    hooks[event] = keep + [{"hooks": [{"type": "command", "command": command, "timeout": timeout}]}]


def _drop_hooks(hooks: Dict[str, Any], event: str):
    keep = [h for h in hooks.get(event, []) if "agent_comms" not in json.dumps(h)]
    if keep:
        hooks[event] = keep
    else:
        hooks.pop(event, None)


def hook_command(python: str, agent: str) -> str:
    return f'"{python}" -m agent_comms.cli autosave --agent {agent}'


def install_claude(home: Path, python: str):
    path = home / ".claude" / "settings.json"
    data = _read_json(path)
    hooks = data.setdefault("hooks", {})
    _drop_hooks(hooks, "PreToolUse")
    _set_hook(hooks, "Stop", hook_command(python, "claude"))
    _write_json(path, data)
    return path


def install_codex(home: Path, python: str, alias: str):
    hooks_path = home / ".codex" / "hooks.json"
    data = _read_json(hooks_path)
    _set_hook(data.setdefault("hooks", {}), "Stop", hook_command(python, "codex"))
    _write_json(hooks_path, data)

    config = home / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    if "[mcp_servers.agent-comms]" not in text:
        py = python.replace("\\", "\\\\")
        text += (
            f'\n[mcp_servers.agent-comms]\ncommand = "{py}"\nargs = ["-m", "agent_comms.cli", "mcp"]\n'
            f'\n[mcp_servers.agent-comms.env]\nAGENT_COMMS_MACHINE_ALIAS = "{alias}"\n'
        )
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(text, encoding="utf-8")
    return hooks_path


def install_gemini(home: Path, python: str, alias: str):
    path = home / ".gemini" / "settings.json"
    data = _read_json(path)
    data.setdefault("mcpServers", {})["agent-comms"] = {
        "command": python,
        "args": ["-m", "agent_comms.cli", "mcp"],
        "env": {"AGENT_COMMS_MACHINE_ALIAS": alias},
    }
    data.setdefault("hooksConfig", {})["enabled"] = True
    _set_hook(data.setdefault("hooks", {}), "AfterAgent", hook_command(python, "gemini"), timeout=30000)
    _write_json(path, data)
    return path


def install_agy(python: str, alias: str):
    subprocess.run(
        ["agy", "mcp", "add", "--env", f"AGENT_COMMS_MACHINE_ALIAS={alias}",
         "agent-comms", python, "-m", "agent_comms.cli", "mcp"],
        capture_output=True,
        check=False,
    )


def install_all(home: Path, alias: str, peers: List[str], python: str = sys.executable) -> List[str]:
    """Installs into every agent found in this home folder. Returns what it did."""
    done: List[str] = []
    guidance = GUIDANCE.format(start=START, end=END, alias=alias, peers=", ".join(peers) or "none yet")

    steps: List[tuple[str, Path, Callable[[], Any]]] = [
        ("Claude Code", home / ".claude", lambda: install_claude(home, python)),
        ("Codex", home / ".codex", lambda: install_codex(home, python, alias)),
        ("Gemini CLI", home / ".gemini", lambda: install_gemini(home, python, alias)),
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
        ("Gemini / Antigravity", home / ".gemini" / "GEMINI.md"),
    ]:
        if md.parent.exists():
            write_block(md, guidance)
            done.append(f"{name}: instructions in {md}")

    try:
        install_agy(python, alias)
        done.append("Antigravity (agy): MCP")
    except FileNotFoundError:
        pass
    return done
