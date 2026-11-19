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
import time
from typing import Dict, Optional

from agent_comms.config import config_manager

DEFAULTS = {"cap_cpu_percent": 85, "cap_running_agents": 4, "cap_min_free_mb": 1024, "cap_mb_per_job": 400}


def _cap(name: str) -> float:
    return float(config_manager.get(name) or DEFAULTS[name])


def _powershell(command: str) -> str:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=20,
    )
    return res.stdout.strip()


def _linux_cpu() -> float:
    def sample():
        values = [int(v) for v in open("/proc/stat", encoding="utf-8").readline().split()[1:]]
        return values[3] + values[4], sum(values)
    idle1, total1 = sample()
    time.sleep(1)
    idle2, total2 = sample()
    return 100 * (1 - (idle2 - idle1) / max(total2 - total1, 1))


def cpu_percent() -> Optional[float]:
    """Real CPU use across all cores, 0-100."""
    system = platform.system()
    try:
        if system == "Linux":
            return _linux_cpu()
        if system == "Darwin":
            out = subprocess.run(["ps", "-A", "-o", "%cpu="], capture_output=True, text=True, timeout=10).stdout
            return sum(float(v) for v in out.split()) / (os.cpu_count() or 1)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
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
    """Helper jobs running on this machine: ones it started itself plus ones sent here over SSH.
    Agent apps and chats the user has open don't count; they would keep the machine busy forever."""
    from agent_comms.fleet.runner import running_incoming_jobs, running_local_jobs
    return running_local_jobs() + running_incoming_jobs()


def check() -> Dict[str, object]:
    """Returns this machine's load and the reason it is busy, if it is."""
    cpu, free, agents = cpu_percent(), free_memory_mb(), running_agents()
    reason = None
    if config_manager.get("accept_work") is False:
        reason = "switched off (agent-comms config set accept_work true to turn back on)"
    elif cpu is not None and cpu > _cap("cap_cpu_percent"):
        reason = f"CPU at {cpu:.0f}% (cap {_cap('cap_cpu_percent'):.0f}%)"
    elif free is not None and free - agents * _cap("cap_mb_per_job") < _cap("cap_min_free_mb"):
        # Jobs that just started haven't used their memory yet, so set some aside for each.
        reason = (f"only {free:.0f} MB free memory with {agents} helper jobs running "
                  f"(cap {_cap('cap_min_free_mb'):.0f} MB + {_cap('cap_mb_per_job'):.0f} MB per job)")
    elif agents >= _cap("cap_running_agents"):
        reason = f"{agents} helper jobs already running (cap {_cap('cap_running_agents'):.0f})"
    return {
        "busy": reason is not None,
        "reason": reason,
        "cpu_percent": None if cpu is None else round(cpu),
        "free_memory_mb": None if free is None else round(free),
        "running_agents": agents,
    }
