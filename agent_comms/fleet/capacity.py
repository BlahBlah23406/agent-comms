"""
Machine Capacity
================
Decides if this machine is too busy to take helper work: CPU, free memory,
how many agent CLIs are already running, or switched off by hand.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Dict, Optional

from agent_comms.config import config_manager

AGENT_NAMES = {"claude", "codex", "agy", "gemini", "ollama"}
DEFAULTS = {"cap_cpu_percent": 85, "cap_running_agents": 6, "cap_min_free_mb": 1024}


def _cap(name: str) -> float:
    return float(config_manager.get(name) or DEFAULTS[name])


def _powershell(command: str) -> str:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=20,
    )
    return res.stdout.strip()


def cpu_percent() -> Optional[float]:
    if hasattr(os, "getloadavg"):
        return os.getloadavg()[0] / (os.cpu_count() or 1) * 100
    try:
        return float(_powershell(
            "((Get-Counter '\\Processor(_Total)\\% Processor Time' -SampleInterval 1 -MaxSamples 3)"
            ".CounterSamples.CookedValue | Measure-Object -Average).Average"
        ))
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def free_memory_mb() -> Optional[float]:
    system = platform.system()
    try:
        if system == "Linux":
            for line in open("/proc/meminfo", encoding="utf-8"):
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
        elif system == "Windows":
            return float(_powershell("(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory")) / 1024
        elif system == "Darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
            pages = {}
            for line in out.splitlines()[1:]:
                key, _, value = line.partition(":")
                pages[key.strip()] = int(value.strip().rstrip(".") or 0)
            size = 16384 if platform.machine() == "arm64" else 4096
            free = pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)
            return free * size / 1024 / 1024
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    return None


def running_agents() -> int:
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=20).stdout
            names = [line.split(",")[0].strip('"').lower().removesuffix(".exe") for line in out.splitlines() if line]
        else:
            out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=10).stdout
            names = [os.path.basename(line.strip()).lower() for line in out.splitlines()]
    except (OSError, subprocess.SubprocessError):
        return 0
    return sum(1 for n in names if n in AGENT_NAMES)


def check() -> Dict[str, object]:
    """Returns this machine's load and the reason it is busy, if it is."""
    cpu, free, agents = cpu_percent(), free_memory_mb(), running_agents()
    reason = None
    if config_manager.get("accept_work") is False:
        reason = "switched off (agent-comms config set accept_work true to turn back on)"
    elif cpu is not None and cpu > _cap("cap_cpu_percent"):
        reason = f"CPU at {cpu:.0f}% (cap {_cap('cap_cpu_percent'):.0f}%)"
    elif free is not None and free < _cap("cap_min_free_mb"):
        reason = f"only {free:.0f} MB free memory (cap {_cap('cap_min_free_mb'):.0f} MB)"
    elif agents >= _cap("cap_running_agents"):
        reason = f"{agents} agent CLIs already running (cap {_cap('cap_running_agents'):.0f})"
    return {
        "busy": reason is not None,
        "reason": reason,
        "cpu_percent": None if cpu is None else round(cpu),
        "free_memory_mb": None if free is None else round(free),
        "running_agents": agents,
    }
