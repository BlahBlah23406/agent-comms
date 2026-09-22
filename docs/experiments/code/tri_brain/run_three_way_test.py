"""
Tri-Brain 3-Way Master Orchestrator
===================================
Runs a real-time distributed mesh simultaneously across 3 physical devices:
1. Windows 11 (Providence) - Local process
2. macOS Apple Silicon (The-Triskelion) - Over Tailscale SSH
3. Ubuntu Linux 24.04 (code-47) - Over Tailscale / Direct SSH
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


async def run_three_way_test():
    print("=" * 80)
    print("STARTING 3-WAY LIVE TRI-BRAIN TEST")
    print("=" * 80)
    print("Node 1: Providence (Windows 11)")
    print("Node 2: The-Triskelion (macOS Apple Silicon ARM64)")
    print("Node 3: code-47 (Oracle Cloud Ubuntu Linux x86_64)")
    print("Relay Hub: ws://<relay-host>:8765/ws")
    print("=" * 80)

    # 1. Copy node_mac.py to The-Triskelion
    print("\n[Orchestrator] Synchronizing node_mac.py to The-Triskelion...")
    mac_script = str(PROJECT_ROOT / "tests" / "tri_brain" / "node_mac.py")
    subprocess.run(
        f'scp -i <ssh-key-path> "{mac_script}" the-triskelion:/tmp/node_mac.py',
        shell=True,
        check=True,
    )

    # 2. Copy node_linux.py to code-47
    print("[Orchestrator] Synchronizing node_linux.py to code-47...")
    linux_script = str(PROJECT_ROOT / "tests" / "tri_brain" / "node_linux.py")
    subprocess.run(
        f'scp -i <ssh-key-path> "{linux_script}" ubuntu@<linux-node-host>:/tmp/node_linux.py',
        shell=True,
        check=True,
    )

    print("\n[Orchestrator] Launching all 3 nodes concurrently across the WAN...")

    # Launch Linux Node
    cmd_linux = [
        "ssh",
        "-i",
        "<ssh-key-path>",
        "-n",
        "-o",
        "StrictHostKeyChecking=no",
        "ubuntu@<linux-node-host>",
        "python3 /tmp/node_linux.py",
    ]
    proc_linux = await asyncio.create_subprocess_exec(
        *cmd_linux,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # Launch Mac Node
    cmd_mac = [
        "ssh",
        "-i",
        "<ssh-key-path>",
        "-n",
        "-o",
        "StrictHostKeyChecking=no",
        "the-triskelion",
        "/Users/shaya/agent-comms/venv/bin/python /tmp/node_mac.py",
    ]
    proc_mac = await asyncio.create_subprocess_exec(
        *cmd_mac,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # Launch Windows Node (Local)
    cmd_windows = [
        sys.executable,
        str(PROJECT_ROOT / "tests" / "tri_brain" / "node_windows.py"),
    ]
    proc_windows = await asyncio.create_subprocess_exec(
        *cmd_windows,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # Stream outputs with prefixes
    async def stream_output(prefix, reader):
        while True:
            line = await reader.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            print(f"[{prefix:<10}] {text}", flush=True)

    await asyncio.gather(
        stream_output("WIN11", proc_windows.stdout),
        stream_output("MACOS", proc_mac.stdout),
        stream_output("LINUX", proc_linux.stdout),
        proc_windows.wait(),
        proc_mac.wait(),
        proc_linux.wait(),
    )

    print("\n" + "=" * 80)
    print("3-WAY TRI-BRAIN EXECUTION COMPLETED")
    print(f"Windows Exit Code: {proc_windows.returncode}")
    print(f"macOS Exit Code:   {proc_mac.returncode}")
    print(f"Linux Exit Code:   {proc_linux.returncode}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_three_way_test())
