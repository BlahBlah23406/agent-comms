"""
Agent Communication Suite CLI
=============================
Unified command-line interface for Context Capsules, Live Relay, and MCP integration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import List
import uvicorn
from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.models.capsule import EpistemicLearning, LearningCategory
from agent_comms.relay.client import AgentRelayClient
from agent_comms.relay.server import create_app


def handle_capsule_pack(args):
    packager = CapsulePackager(workspace_path=Path(args.dir) if args.dir else None)
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)

    learnings = []
    if args.learning:
        for item in args.learning:
            # format: category:summary (e.g. finding:Redis url requires ssl)
            if ":" in item:
                cat_str, summary = item.split(":", 1)
                try:
                    cat = LearningCategory(cat_str.lower().strip())
                except ValueError:
                    cat = LearningCategory.FINDING
            else:
                cat = LearningCategory.FINDING
                summary = item
            learnings.append(EpistemicLearning(category=cat, summary=summary))

    capsule = packager.package(
        task_id=args.task,
        title=args.title or args.task,
        executive_summary=args.summary,
        goal=args.goal or args.summary,
        next_action=args.next,
        epistemic_learnings=learnings,
        agent_name=args.agent_name or "CLI-User",
        target_agent=args.target,
    )

    if args.output:
        out_p = Path(args.output).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(capsule.model_dump_json(indent=2), encoding="utf-8")
        saved_path = out_p
    else:
        saved_path = store.save(capsule)

    print(f"\n[+] Capsule successfully generated: {capsule.capsule_id}")
    print(f"[+] Stored at: {saved_path}")
    print(f"[+] Files modified: {len(capsule.workspace.modified_files)}")
    print(f"[+] Untracked files: {len(capsule.workspace.untracked_files)}")
    print("\n" + "=" * 60)
    print(capsule.to_briefing_markdown())
    print("=" * 60)


def handle_capsule_unpack(args):
    unpacker = CapsuleUnpacker(workspace_path=Path(args.dir) if args.dir else None)
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)

    target = args.capsule
    capsule = None

    p = Path(target)
    if p.exists() and p.is_file():
        capsule = store.load_from_file(p)
    else:
        capsule = store.load_by_id(target)

    if not capsule:
        print(f"[-] Error: Could not locate capsule '{target}'")
        sys.exit(1)

    result = unpacker.apply(capsule, apply_workspace=not args.no_patch)
    print(f"\n[+] Unpacked Capsule: {capsule.capsule_id} for Task: {capsule.task_id}")
    print(f"[+] Patch Status: {result['git_patch_message']}")
    if result["untracked_files_restored"]:
        print(f"[+] Restored Files: {', '.join(result['untracked_files_restored'])}")
    print("\n" + "=" * 60)
    print("RESUMPTION BRIEFING FOR AGENT:")
    print("=" * 60)
    print(result["briefing_markdown"])
    print("=" * 60)


def handle_capsule_list(args):
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)
    capsules = store.list_capsules()
    if not capsules:
        print("No capsules found in store.")
        return

    print(f"\nFound {len(capsules)} capsule(s):\n")
    print(f"{'CAPSULE ID':<26} {'TASK ID':<20} {'TIMESTAMP':<24} {'SUMMARY'}")
    print("-" * 90)
    for c in capsules:
        print(f"{c.capsule_id:<26} {c.task_id:<20} {c.created_at[:19]:<24} {c.executive_summary[:30]}...")


def handle_capsule_show(args):
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)
    target = args.capsule
    p = Path(target)
    if p.exists() and p.is_file():
        c = store.load_from_file(p)
    else:
        c = store.load_by_id(target)
    if not c:
        print(f"[-] Capsule '{target}' not found.")
        sys.exit(1)
    print(c.to_briefing_markdown())


def handle_capsule_push(args):
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)
    try:
        location = store.push_to_cloud(args.capsule, provider_name=args.cloud)
        print(f"\n[+] Successfully pushed capsule '{args.capsule}' to cloud!")
        print(f"[+] Remote Location: {location}")
    except Exception as e:
        print(f"[-] Push failed: {e}")
        sys.exit(1)


def handle_capsule_pull(args):
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)
    unpacker = CapsuleUnpacker(workspace_path=Path(args.dir) if args.dir else None)
    try:
        capsule = store.pull_from_cloud(args.capsule, provider_name=args.cloud, save_local=True)
        print(f"\n[+] Successfully pulled capsule '{capsule.capsule_id}' for task '{capsule.task_id}'!")
        if args.apply:
            res = unpacker.apply(capsule, apply_workspace=True)
            print(f"[+] Patch Status: {res['git_patch_message']}")
            if res["untracked_files_restored"]:
                print(f"[+] Restored Files: {', '.join(res['untracked_files_restored'])}")
        print("\n" + "=" * 60)
        print("RESUMPTION BRIEFING:")
        print("=" * 60)
        print(capsule.to_briefing_markdown())
        print("=" * 60)
    except Exception as e:
        print(f"[-] Pull failed: {e}")
        sys.exit(1)


def handle_capsule_cloud_list(args):
    store = CapsuleStore(base_dir=Path(args.store) if args.store else None)
    try:
        caps = store.list_cloud_capsules(provider_name=args.cloud)
        if not caps:
            print("No remote capsules found.")
            return
        print(f"\nFound {len(caps)} cloud capsule(s):\n")
        print(f"{'CAPSULE ID':<26} {'TASK ID':<20} {'PROVIDER':<10} {'LOCATION'}")
        print("-" * 90)
        for c in caps:
            print(f"{c.capsule_id:<26} {c.task_id:<20} {c.provider:<10} {c.location}")
    except Exception as e:
        print(f"[-] Error listing cloud capsules: {e}")
        sys.exit(1)


def handle_relay_server(args):
    print(f"[+] Starting AHRP Relay Server on {args.host}:{args.port}...")
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", ws_max_size=32 * 1024 * 1024)


async def _run_relay_peers(relay_url: str):
    client = AgentRelayClient(agent_id="cli-peer-checker", relay_url=relay_url)
    await client.connect()
    peers = await client.list_peers()
    print(f"\n[+] Online Agents on {relay_url} ({len(peers)} connected):")
    for p in peers:
        print(f" - Agent: {p.agent_id} | Host: {p.machine_id} | Framework: {p.framework} | Caps: {', '.join(p.capabilities)}")
    await client.disconnect()


def handle_relay_peers(args):
    asyncio.run(_run_relay_peers(args.relay))


async def _run_relay_send(args):
    client = AgentRelayClient(agent_id=args.sender or "cli-sender", relay_url=args.relay)
    await client.connect()
    payload = {"text": args.message}
    if args.topic:
        await client.publish(args.topic, payload)
        print(f"[+] Published message to topic '{args.topic}'")
    elif args.target:
        await client.send_message(args.target, payload)
        print(f"[+] Sent direct message to agent '{args.target}'")
    else:
        print("[-] Specify either --topic or --target")
    await client.disconnect()


def handle_relay_send(args):
    asyncio.run(_run_relay_send(args))


async def _run_relay_rpc(args):
    client = AgentRelayClient(agent_id="cli-rpc-caller", relay_url=args.relay)
    await client.connect()
    params = json.loads(args.params) if args.params else {}
    print(f"[+] Invoking RPC '{args.method}' on remote agent '{args.target}'...")
    try:
        res = await client.rpc(args.target, args.method, params, timeout=args.timeout)
        print(f"[+] RPC Response:\n{json.dumps(res, indent=2)}")
    except Exception as e:
        print(f"[-] RPC failed: {e}")
    await client.disconnect()


def handle_relay_rpc(args):
    asyncio.run(_run_relay_rpc(args))


def handle_mcp(args):
    from agent_comms.mcp.server import AgentCommsMCPServer
    server = AgentCommsMCPServer(workspace_path=Path(args.dir) if args.dir else None)
    asyncio.run(server.run_stdio())


def handle_p2p_template(args):
    target_dir = Path(args.dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    peer_alpha_code = '''"""
Dual-Brain Peer Alpha (Left Hemisphere)
=======================================
Demonstrates symmetric mental model sharing and runtime cognitive adaptation.
"""
import asyncio
from agent_comms.mesh import DualBrainNode

RELAY_URL = "ws://localhost:8765/ws"

async def main():
    async with DualBrainNode(agent_id="node-alpha", relay_url=RELAY_URL, role="left-hemisphere") as node:
        print("[Node Alpha] Joined mesh. Establishing shared beliefs...")

        # 1. Assert initial domain belief into shared mind
        await node.set_belief("system_mode", "high_throughput", rationale="Batch workload scheduled")
        await node.propose_contract("data_pipeline", {"batch_size": "int", "encryption": "str"})

        # 2. Listen for cognitive deltas from Node Beta
        async def on_delta(key, value, rationale):
            print(f"[Node Alpha <- Mind] Cognitive Delta Received! '{key}' = {value} (Rationale: {rationale})")
            if key == "execution_optimization":
                print(f"[Node Alpha] Dynamically adapting execution pipeline: {value}")

        node.on_belief_update(on_delta)

        # 3. Keep running and listening
        print("[Node Alpha] Listening for peer deltas. Press Ctrl+C to stop.")
        await asyncio.sleep(10)

        # 4. Export twin Context Capsule
        capsule = node.export_twin_capsule(task_id="DUAL-BRAIN-QUICKSTART", summary="Dual-brain peer sync completed")
        print(f"[Node Alpha] Persisted twin capsule: {capsule.capsule_id}")

if __name__ == "__main__":
    asyncio.run(main())
'''

    peer_beta_code = '''"""
Dual-Brain Peer Beta (Right Hemisphere)
========================================
Demonstrates peer parity, contract consensus, and asserting cognitive deltas.
"""
import asyncio
from agent_comms.mesh import DualBrainNode

RELAY_URL = "ws://localhost:8765/ws"

async def main():
    async with DualBrainNode(agent_id="node-beta", relay_url=RELAY_URL, role="right-hemisphere") as node:
        print("[Node Beta] Joined mesh. Connecting to shared mind...")

        # 1. Wait a moment for Alpha to publish initial state
        await asyncio.sleep(1)

        # 2. Read shared belief
        mode = node.get_belief("system_mode")
        print(f"[Node Beta] Read shared belief 'system_mode': {mode}")

        # 3. Discover an optimization and assert a cognitive delta
        print("[Node Beta] Discovered optimization: Pre-sorting inputs increases throughput 40%!")
        await node.set_belief("execution_optimization", "enable_vector_presort", rationale="Reduces CPU branch mispredictions")

        # 4. Lock contract by consensus
        await node.lock_contract("data_pipeline", {"batch_size": "int", "encryption": "sha256", "presorted": "bool"})
        print("[Node Beta] Locked contract 'data_pipeline' with consensus.")

        await asyncio.sleep(5)
        capsule = node.export_twin_capsule(task_id="DUAL-BRAIN-QUICKSTART", summary="Dual-brain right hemisphere completed")
        print(f"[Node Beta] Persisted twin capsule: {capsule.capsule_id}")

if __name__ == "__main__":
    asyncio.run(main())
'''

    runner_code = '''"""
Dual-Brain Local Runner
=======================
Spawns AHRP relay in background and executes Node Alpha and Node Beta concurrently.
"""
import asyncio
import subprocess
import sys
import time

def main():
    print("=" * 60)
    print("Dual-Brain Mesh Quickstart")
    print("=" * 60)
    print("1. Ensure AHRP relay is running: agent-comms relay server --port 8765")
    print("2. In Terminal 1: python peer_alpha.py")
    print("3. In Terminal 2: python peer_beta.py")
    print("=" * 60)

if __name__ == "__main__":
    main()
'''

    (target_dir / "peer_alpha.py").write_text(peer_alpha_code, encoding="utf-8")
    (target_dir / "peer_beta.py").write_text(peer_beta_code, encoding="utf-8")
    (target_dir / "quickstart.py").write_text(runner_code, encoding="utf-8")

    print(f"\n[+] Successfully scaffolded Dual-Brain template in: {target_dir}")
    print("  - peer_alpha.py   (Left Hemisphere node)")
    print("  - peer_beta.py    (Right Hemisphere node)")
    print("  - quickstart.py   (Usage instructions)")
    print("\nTo run:")
    print("  1. Start relay:  agent-comms relay server --port 8765")
    print("  2. Run peers:    python peer_alpha.py & python peer_beta.py\n")



def _setup_standby_service(alias: str, python_exe: str, home: Path):
    system = platform.system()
    print(f"\n[+] Configuring background standby auto-wake service on {system}...")
    if system == "Linux":
        svc_dir = home / ".config" / "systemd" / "user"
        svc_dir.mkdir(parents=True, exist_ok=True)
        svc_file = svc_dir / "agent-comms-standby.service"
        content = f"""[Unit]
Description=Agent Comms Standby Node ({alias})
After=network.target

[Service]
ExecStart={python_exe} -m agent_comms.cli standby --name {alias}
Restart=always
RestartSec=5
Environment=AGENT_COMMS_MACHINE_ALIAS={alias}

[Install]
WantedBy=default.target
"""
        svc_file.write_text(content, encoding="utf-8")
        print(f"[+] Created systemd user service at: {svc_file}")
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
            subprocess.run(["systemctl", "--user", "enable", "--now", "agent-comms-standby"], capture_output=True, check=False)
            print("[+] Enabled and started agent-comms-standby service!")
        except Exception:
            print("    To activate: systemctl --user enable --now agent-comms-standby")

    elif system == "Darwin":
        launch_dir = home / "Library" / "LaunchAgents"
        launch_dir.mkdir(parents=True, exist_ok=True)
        plist_file = launch_dir / "com.agentcomms.standby.plist"
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agentcomms.standby</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>-m</string>
        <string>agent_comms.cli</string>
        <string>standby</string>
        <string>--name</string>
        <string>{alias}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
        plist_file.write_text(content, encoding="utf-8")
        print(f"[+] Created LaunchAgent plist at: {plist_file}")
        try:
            subprocess.run(["launchctl", "load", "-w", str(plist_file)], capture_output=True, check=False)
            print("[+] Loaded com.agentcomms.standby LaunchAgent!")
        except Exception:
            print(f"    To activate: launchctl load -w {plist_file}")

    elif system == "Windows":
        bat_file = home / ".agent-comms" / "start_standby.bat"
        bat_content = f"""@echo off
set AGENT_COMMS_MACHINE_ALIAS={alias}
"{python_exe}" -m agent_comms.cli standby --name {alias}
"""
        bat_file.write_text(bat_content, encoding="utf-8")
        print(f"[+] Created standby batch runner at: {bat_file}")
        startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if startup_dir.exists():
            vbs_file = startup_dir / "AgentCommsStandby.vbs"
            vbs_content = f'CreateObject("WScript.Shell").Run """{bat_file}""", 0, False'
            try:
                vbs_file.write_text(vbs_content, encoding="utf-8")
                print(f"[+] Added silent auto-start runner to Windows Startup: {vbs_file}")
            except Exception:
                pass


def handle_setup(args):
    print("=" * 65)
    print("  Agent Comms: Automated Environment & MCP Setup")
    print("=" * 65)
    home = Path.home()
    python_exe = sys.executable

    # 1. Resolve Machine Identity & Peers
    alias = getattr(args, "alias", None) or os.environ.get("AGENT_COMMS_MACHINE_ALIAS") or socket.gethostname()
    peers_raw = getattr(args, "peers", None)
    if peers_raw:
        peers = [p.strip() for p in peers_raw.split(",") if p.strip()]
    else:
        peers = ["code-47", "triskelion", "providence"]
    if alias not in peers:
        peers.append(alias)

    cloud_provider = getattr(args, "cloud", "relay")

    # 2. Update ~/.agent-comms/config.json
    cfg_dir = home / ".agent-comms"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.json"
    cfg_data = {}
    if cfg_path.exists():
        try:
            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg_data = {}
    cfg_data["machine_alias"] = alias
    cfg_data["known_peers"] = peers
    cfg_data["default_cloud_provider"] = cloud_provider
    cfg_path.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
    print(f"[+] Configured Machine Node Identity: '{alias}'")
    print(f"[+] Known Peer Nodes: {', '.join(peers)}")

    # 3. Initialize local capsule store
    store_dir = cfg_dir / "capsules"
    store_dir.mkdir(parents=True, exist_ok=True)
    print(f"[+] Initialized Context Capsule storage at: {store_dir}")

    # 4. Configure Claude Code (~/.claude.json & claude CLI)
    claude_code_config = home / ".claude.json"
    if claude_code_config.exists() or (home / ".claude").exists():
        try:
            cc_data = {}
            if claude_code_config.exists():
                try:
                    cc_data = json.loads(claude_code_config.read_text(encoding="utf-8"))
                except Exception:
                    cc_data = {}
            if "mcpServers" not in cc_data:
                cc_data["mcpServers"] = {}
            cc_data["mcpServers"]["agent-comms"] = {
                "type": "stdio",
                "command": python_exe,
                "args": ["-m", "agent_comms.cli", "mcp"],
                "env": {"AGENT_COMMS_MACHINE_ALIAS": alias},
            }
            claude_code_config.write_text(json.dumps(cc_data, indent=2), encoding="utf-8")
            print(f"[+] Configured Claude Code MCP in: {claude_code_config}")
        except Exception as e:
            print(f"[!] Warning updating Claude Code config: {e}")

        # Also invoke claude CLI if in PATH
        try:
            subprocess.run(
                ["claude", "mcp", "add", "--scope", "user", "agent-comms", "--env", f"AGENT_COMMS_MACHINE_ALIAS={alias}", "--", python_exe, "-m", "agent_comms.cli", "mcp"],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass

    # 5. Configure Claude Desktop
    cur_os = platform.system()
    claude_paths = []
    if cur_os == "Darwin":
        claude_paths.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    elif cur_os == "Windows" and os.environ.get("APPDATA"):
        claude_paths.append(Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json")
    elif cur_os == "Linux":
        claude_paths.append(home / ".config" / "Claude" / "claude_desktop_config.json")

    for c_path in claude_paths:
        try:
            c_data = {}
            if c_path.exists():
                try:
                    c_data = json.loads(c_path.read_text(encoding="utf-8"))
                except Exception:
                    c_data = {}
            if "mcpServers" not in c_data:
                c_data["mcpServers"] = {}
            c_data["mcpServers"]["agent-comms"] = {
                "command": python_exe,
                "args": ["-m", "agent_comms.cli", "mcp"],
                "env": {"AGENT_COMMS_MACHINE_ALIAS": alias},
            }
            c_path.parent.mkdir(parents=True, exist_ok=True)
            c_path.write_text(json.dumps(c_data, indent=2), encoding="utf-8")
            print(f"[+] Configured Claude Desktop MCP at: {c_path}")
        except Exception as e:
            print(f"[!] Warning updating Claude config ({c_path}): {e}")

    # 6. Configure Claude Global Guidelines (~/.claude/CLAUDE.md)
    claude_dir = home / ".claude"
    try:
        claude_dir.mkdir(parents=True, exist_ok=True)
        claude_md = claude_dir / "CLAUDE.md"
        claude_guidelines = f"""# Claude Code Global Guidelines: Distributed Agent Collaboration & Context Capsules

You have access to the **`agent-comms`** MCP server (`agent-comms`), enabling cross-machine collaboration, zero-loss task handoffs, cloud synchronization, and preemptive quota protection.

## Machine Identity & Mesh Network
- **Current Machine Node:** `{alias}`
- **Known Peer Network Nodes:** {', '.join(peers)}

## Available Capabilities & Procedures
1. **Preemptive AI Quota & Rate-Limit Guard:**
   - If approaching rate-limit thresholds (hourly, weekly, or request limit), call `preemptive_quota_evacuate` BEFORE reaching a 429 lockout.
   - This freezes uncommitted changes, untracked files, and epistemic learnings into a Context Capsule with a tailored resumption prompt for a successor provider (e.g. Claude -> Gemini) or peer node.

2. **Active Cross-Session Collaboration:**
   - To start a real-time collaborative session with peer machines: call `start_cross_session(session_id="...", target_machine="<peer-alias>")`.
   - The framework automatically wakes the peer machine over LAN UDP (port 8764), restores code context, and links both machines into a real-time dual-brain cognitive session.
   - Use `scan_network_peers()` to discover online or standby nodes.

3. **Context Capsule Handoff & Cloud Sync:**
   - To save progress across sessions or before logging off: `push_handoff_capsule(...)`.
   - To resume a task from another machine or cloud: `pull_handoff_capsule(capsule_id="...", apply_workspace=True)`.
   - To check saved capsules: `list_cloud_capsules()` or `list_saved_capsules()`.
"""
        claude_md.write_text(claude_guidelines, encoding="utf-8")
        print(f"[+] Created Claude Global Guidelines at: {claude_md}")
    except Exception as e:
        logger.debug("Could not write ~/.claude/CLAUDE.md: %s", e)

    # 7. Configure Antigravity / Gemini
    agy_paths = [
        home / ".gemini" / "config" / "mcp_config.json",
        home / ".gemini" / "antigravity" / "mcp_config.json",
    ]
    for a_path in agy_paths:
        if a_path.parent.exists() or (home / ".gemini").exists():
            try:
                a_data = {}
                if a_path.exists():
                    try:
                        a_data = json.loads(a_path.read_text(encoding="utf-8"))
                    except Exception:
                        a_data = {}
                if "mcpServers" not in a_data:
                    a_data["mcpServers"] = {}
                a_data["mcpServers"]["agent-comms"] = {
                    "command": python_exe,
                    "args": ["-m", "agent_comms.cli", "mcp"],
                    "env": {"AGENT_COMMS_MACHINE_ALIAS": alias},
                }
                a_path.parent.mkdir(parents=True, exist_ok=True)
                a_path.write_text(json.dumps(a_data, indent=2), encoding="utf-8")
                print(f"[+] Configured Antigravity MCP at: {a_path}")
            except Exception as e:
                print(f"[!] Warning updating Antigravity config ({a_path}): {e}")

    # Also try invoking agy CLI if available
    try:
        subprocess.run(
            ["agy", "mcp", "add", "--env", f"AGENT_COMMS_MACHINE_ALIAS={alias}", "agent-comms", python_exe, "-m", "agent_comms.cli", "mcp"],
            capture_output=True,
            check=False,
        )
    except Exception:
        pass

    # 8. Configure Cursor
    cursor_paths = [
        home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
        home / ".cursor" / "mcp.json",
    ]
    for cur_path in cursor_paths:
        if cur_path.parent.exists():
            try:
                cur_data = {}
                if cur_path.exists():
                    try:
                        cur_data = json.loads(cur_path.read_text(encoding="utf-8"))
                    except Exception:
                        cur_data = {}
                if "mcpServers" not in cur_data:
                    cur_data["mcpServers"] = {}
                cur_data["mcpServers"]["agent-comms"] = {
                    "command": python_exe,
                    "args": ["-m", "agent_comms.cli", "mcp"],
                    "env": {"AGENT_COMMS_MACHINE_ALIAS": alias},
                }
                cur_path.write_text(json.dumps(cur_data, indent=2), encoding="utf-8")
                print(f"[+] Configured Cursor MCP at: {cur_path}")
            except Exception:
                pass

    # 9. Standby Service (Auto-Wake Background Daemon)
    if getattr(args, "standby", False):
        _setup_standby_service(alias, python_exe, home)

    print("=" * 65)
    print("  Setup Complete! Ready to use across AGY & Claude.")
    print(f"  Node '{alias}' is fully integrated with peer network.")
    print("=" * 65)


async def _run_demo():
    import socket
    from agent_comms.mesh import DualBrainNode

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    print("=" * 70)
    print("  AGENT COMMS: LIVE DUAL-BRAIN MESH DEMO")
    print("=" * 70)
    print(f"[+] Spawning in-process AHRP Relay on port {port}...")

    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    for _ in range(25):
        if server.started:
            break
        await asyncio.sleep(0.1)

    relay_url = f"ws://127.0.0.1:{port}/ws"

    print("[+] Connecting Node Alpha (Left Hemisphere)...")
    node_alpha = DualBrainNode(agent_id="node-alpha", relay_url=relay_url, role="left-hemisphere")
    await node_alpha.start()

    print("[+] Connecting Node Beta (Right Hemisphere)...")
    node_beta = DualBrainNode(agent_id="node-beta", relay_url=relay_url, role="right-hemisphere")
    await node_beta.start()

    print("\n--- PHASE 1: INITIAL BELIEF SHARING ---")
    await node_alpha.set_belief("dataset_mode", "streaming_pipeline", rationale="High throughput requested")
    await asyncio.sleep(0.2)
    print(f"Node Beta read belief 'dataset_mode': {node_beta.get_belief('dataset_mode')}")

    print("\n--- PHASE 2: DYNAMIC RUNTIME COGNITIVE DELTA ---")
    async def on_delta(key, val, rationale):
        print(f"* [Node Alpha <- Mind] Cognitive Delta: '{key}' = {val} | Rationale: {rationale}")
        print(f"   Node Alpha dynamically adapted its live pipeline without restart!")

    node_alpha.on_belief_update(on_delta)

    print("Node Beta discovered hardware optimization: vector presorting reduces CPU branch mispredictions.")
    await node_beta.set_belief("presort_optimization", True, rationale="35% faster execution on x86_64")
    await asyncio.sleep(0.3)

    print("\n--- PHASE 3: SYMMETRIC CONTRACT CONSENSUS ---")
    await node_alpha.propose_contract("data_contract", {"batch_size": "int", "vectors": "List[float]"})
    await asyncio.sleep(0.1)
    await node_beta.lock_contract("data_contract", {"batch_size": "int", "vectors": "List[float]", "presorted": "bool"})
    print("Locked contract 'data_contract' with mutual consensus!")

    print("\n--- PHASE 4: TWIN CONTEXT CAPSULE PERSISTENCE ---")
    cap_a = node_alpha.export_twin_capsule("DEMO-01", summary="Alpha demo complete")
    cap_b = node_beta.export_twin_capsule("DEMO-01", summary="Beta demo complete")
    print(f"[+] Node Alpha Context Capsule: {cap_a.capsule_id} ({len(cap_a.epistemic_learnings)} learnings)")
    print(f"[+] Node Beta Context Capsule:  {cap_b.capsule_id} ({len(cap_b.epistemic_learnings)} learnings)")

    await node_alpha.stop()
    await node_beta.stop()
    server.should_exit = True
    await server_task

    print("\n" + "=" * 70)
    print("  DEMO COMPLETE: Two Agents Acted As One Mind!")
    print("=" * 70)


def handle_demo(args):
    asyncio.run(_run_demo())


def handle_standby(args):
    from agent_comms.session.standby import StandbyNode
    node = StandbyNode(
        machine_alias=args.name,
        discovery_port=args.port,
        relay_url=args.relay,
        workspace_path=Path(args.dir) if args.dir else None,
    )
    try:
        asyncio.run(node.run_until_interrupted())
    except KeyboardInterrupt:
        print("\n[*] Standby mode stopped by user.")


def handle_session_start(args):
    from agent_comms.session.manager import CrossSessionManager
    mgr = CrossSessionManager(
        machine_alias=args.name,
        workspace_path=Path(args.dir) if args.dir else None,
        discovery_port=args.discovery_port,
    )

    async def _run():
        session = await mgr.start_session(
            session_id=args.room,
            target_machine=args.target,
            capsule_or_id=args.capsule,
            relay_port=args.port,
            external_relay_url=args.relay,
            timeout=args.timeout,
        )
        print("[*] Active session is live. Press Ctrl+C to disconnect and close session.")
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n[*] Closing active cross-session...")
            await session.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


def handle_session_join(args):
    from agent_comms.mesh.node import DualBrainNode
    import socket
    alias = args.name or socket.gethostname()

    async def _run():
        node = DualBrainNode(
            agent_id=f"agent-{alias}",
            relay_url=args.relay_url,
            machine_id=alias,
            role="cross-session-peer",
        )
        print(f"[+] Connecting to cross-session at {args.relay_url}...")
        await node.start()
        print(f"[+] Successfully joined cross-session! Mental model synced.")
        print("[*] Press Ctrl+C to leave session.")
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            await node.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


def handle_session_peers(args):
    from agent_comms.session.discovery import UDPDiscoveryBroadcaster
    bc = UDPDiscoveryBroadcaster(port=args.port)
    print(f"[*] Scanning LAN for standby machines on UDP:{args.port}...")
    peers = asyncio.run(bc.discover_peers(timeout=args.timeout))
    if not peers:
        print("No standby machines detected on LAN.")
        return
    print(f"\n[+] Discovered {len(peers)} standby machine(s):")
    print(f"{'ALIAS':<20} {'IP ADDRESS':<16} {'OS':<10} {'STATUS'}")
    print("-" * 60)
    for p in peers:
        print(f"{p.machine_alias:<20} {p.ip:<16} {p.os_name:<10} {p.status}")


def handle_config_show(args):
    from agent_comms.config import config_manager
    print(json.dumps(config_manager.get_all(), indent=2))


def handle_config_set(args):
    from agent_comms.config import config_manager
    config_manager.set(args.key, args.value)
    print(f"[+] Successfully set '{args.key}' = '{args.value}'")


def handle_config_get(args):
    from agent_comms.config import config_manager
    val = config_manager.get(args.key)
    print(f"{args.key} = {val}")


def handle_quota_status(args):
    from agent_comms.quota.guard import QuotaGuard
    guard = QuotaGuard()
    providers = [args.provider.lower()] if args.provider else ["anthropic", "openai", "gemini", "cursor"]
    print("\n" + "=" * 70)
    print("AI PROVIDER QUOTA & RATE LIMIT HEALTH")
    print("=" * 70)
    for p in providers:
        st = guard.check_quota(p)
        status_label = "RATE LIMITED (429)" if st.is_rate_limited else ("CRITICAL (Evacuate)" if st.is_critical else ("WARNING" if st.is_warning else "HEALTHY"))
        print(f"\nProvider: {p.upper()} [{status_label}]")
        print(f"  Window: {st.window.value} | Requests: {st.requests_used}/{st.max_requests or 'unlimited'} ({st.request_utilization * 100:.1f}%)")
        print(f"  Tokens: {st.tokens_used}/{st.max_tokens or 'unlimited'} ({st.token_utilization * 100:.1f}%)")
        if st.remaining_requests is not None:
            print(f"  Remaining Requests: {st.remaining_requests}")
        if st.reset_at:
            print(f"  Reset At: {st.reset_at}")
        if st.reason:
            print(f"  Notice: {st.reason}")
    print("\n" + "=" * 70)


def handle_quota_set_budget(args):
    from agent_comms.quota.tracker import quota_tracker
    from agent_comms.quota.models import QuotaBudget, QuotaWindow
    b = QuotaBudget(
        provider=args.provider.lower(),
        window=QuotaWindow(args.window.lower()) if args.window else QuotaWindow.HOUR,
        max_requests=args.max_requests,
        max_tokens=args.max_tokens,
    )
    quota_tracker.set_budget(b)
    print(f"[+] Budget for '{args.provider}' updated successfully.")


def handle_quota_record(args):
    from agent_comms.quota.tracker import quota_tracker
    quota_tracker.record_usage(args.provider.lower(), tokens=args.tokens or 0, requests=args.requests or 1)
    print(f"[+] Recorded {args.requests or 1} request(s), {args.tokens or 0} token(s) for '{args.provider}'.")


def handle_quota_evacuate(args):
    from agent_comms.quota.guard import QuotaGuard
    guard = QuotaGuard(workspace_path=Path(args.dir) if args.dir else None)
    res = guard.force_evacuate(
        task_id=args.task,
        provider=args.provider.lower(),
        summary=args.summary or f"Preemptive evacuation before {args.provider} rate limit",
        next_action=args.next,
        target_provider=args.target,
        auto_push_cloud=bool(args.cloud),
        cloud_provider=args.cloud,
    )
    print(f"\n[+] Preemptively evacuated task '{res.task_id}' before '{res.provider}' rate limit!")
    print(f"[+] Context Capsule: {res.capsule_id}")
    print(f"[+] Stored locally at: {res.saved_path}")
    if res.cloud_location:
        print(f"[+] Pushed to cloud: {res.cloud_location}")
    print(f"[+] Target Successor Provider: {res.target_provider or 'Any available agent'}")
    print("\n" + "=" * 60)
    print("RESUMPTION BRIEFING:")
    print("=" * 60)
    print(res.briefing)
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(prog="agent-comms", description="Agent Communication & Handover Protocol Suite")
    subparsers = parser.add_subparsers(dest="command")

    # --- Capsule Subcommands ---
    capsule_parser = subparsers.add_parser("capsule", help="Context Capsule packaging and restoration")
    capsule_subs = capsule_parser.add_subparsers(dest="subcommand")

    # pack
    pack_p = capsule_subs.add_parser("pack", help="Package current workspace and learnings into a capsule")
    pack_p.add_argument("--task", required=True, help="Task or ticket identifier")
    pack_p.add_argument("--title", help="Human-readable title")
    pack_p.add_argument("--summary", required=True, help="Executive summary of work completed")
    pack_p.add_argument("--goal", help="High-level task goal")
    pack_p.add_argument("--next", help="Immediate next action instruction")
    pack_p.add_argument("--learning", action="append", help="Epistemic learning (category:summary)")
    pack_p.add_argument("--target", help="Target agent or machine")
    pack_p.add_argument("--dir", help="Workspace directory (default: current)")
    pack_p.add_argument("--output", help="Explicit output file path")
    pack_p.add_argument("--store", help="Custom capsule store directory")
    pack_p.add_argument("--agent-name", help="Name of current agent")
    pack_p.set_defaults(func=handle_capsule_pack)

    # unpack
    unpack_p = capsule_subs.add_parser("unpack", help="Unpack capsule into workspace")
    unpack_p.add_argument("capsule", help="Capsule ID or file path")
    unpack_p.add_argument("--dir", help="Target workspace directory")
    unpack_p.add_argument("--store", help="Custom capsule store directory")
    unpack_p.add_argument("--no-patch", action="store_true", help="Do not apply git patch/untracked files")
    unpack_p.set_defaults(func=handle_capsule_unpack)

    # push
    push_p = capsule_subs.add_parser("push", help="Push capsule to cloud provider (S3, GCS, Azure, GitHub, Relay)")
    push_p.add_argument("capsule", help="Capsule ID or local JSON file path")
    push_p.add_argument("--cloud", help="Cloud provider (s3, gcs, azure, github, relay)")
    push_p.add_argument("--store", help="Custom capsule store directory")
    push_p.set_defaults(func=handle_capsule_push)

    # pull
    pull_p = capsule_subs.add_parser("pull", help="Pull capsule from cloud provider")
    pull_p.add_argument("capsule", help="Capsule ID or cloud URI")
    pull_p.add_argument("--cloud", help="Cloud provider (s3, gcs, azure, github, relay)")
    pull_p.add_argument("--apply", action="store_true", help="Apply git patch and restore files immediately")
    pull_p.add_argument("--dir", help="Target workspace directory")
    pull_p.add_argument("--store", help="Custom capsule store directory")
    pull_p.set_defaults(func=handle_capsule_pull)

    # cloud-list
    clist_p = capsule_subs.add_parser("cloud-list", help="List capsules available on cloud provider")
    clist_p.add_argument("--cloud", help="Cloud provider (s3, gcs, azure, github, relay)")
    clist_p.add_argument("--store", help="Custom capsule store directory")
    clist_p.set_defaults(func=handle_capsule_cloud_list)

    # list
    list_p = capsule_subs.add_parser("list", help="List locally stored capsules")
    list_p.add_argument("--store", help="Custom capsule store directory")
    list_p.set_defaults(func=handle_capsule_list)

    # show
    show_p = capsule_subs.add_parser("show", help="Display capsule markdown briefing")
    show_p.add_argument("capsule", help="Capsule ID or file path")
    show_p.add_argument("--store", help="Custom capsule store directory")
    show_p.set_defaults(func=handle_capsule_show)

    # --- Standby Daemon Subcommand ---
    standby_p = subparsers.add_parser("standby", help="Run in standby mode on secondary machine to await LAN or relay wake-up")
    standby_p.add_argument("--name", help="Friendly alias for this machine")
    standby_p.add_argument("--port", type=int, default=8764, help="UDP discovery port (default: 8764)")
    standby_p.add_argument("--relay", help="Default relay hub URL")
    standby_p.add_argument("--dir", help="Workspace directory to unpack into")
    standby_p.set_defaults(func=handle_standby)

    # --- Active Cross-Session Subcommands ---
    session_parser = subparsers.add_parser("session", help="Active cross-machine session orchestration")
    session_subs = session_parser.add_subparsers(dest="subcommand")

    # start
    start_p = session_subs.add_parser("start", help="Start active cross-session and automatically wake remote machine(s)")
    start_p.add_argument("--target", help="Specific machine alias to wake (default: all standby peers)")
    start_p.add_argument("--capsule", help="Capsule ID or file to automatically transmit and unpack on remote machine")
    start_p.add_argument("--room", help="Session ID / room name")
    start_p.add_argument("--name", help="Initiator machine alias")
    start_p.add_argument("--port", type=int, default=8765, help="Relay hub port (default: 8765)")
    start_p.add_argument("--discovery-port", type=int, default=8764, help="UDP discovery port (default: 8764)")
    start_p.add_argument("--relay", help="Use external relay hub URL instead of auto-hosting locally")
    start_p.add_argument("--timeout", type=float, default=8.0, help="Wait timeout for remote machine connection")
    start_p.add_argument("--dir", help="Workspace directory")
    start_p.set_defaults(func=handle_session_start)

    # join
    join_p = session_subs.add_parser("join", help="Join an active cross-session via relay URL")
    join_p.add_argument("relay_url", help="Relay WebSocket URL e.g. ws://192.168.1.50:8765/ws")
    join_p.add_argument("--name", help="Machine alias")
    join_p.set_defaults(func=handle_session_join)

    # peers
    peers_p = session_subs.add_parser("peers", help="Scan LAN for standby machines")
    peers_p.add_argument("--port", type=int, default=8764, help="Discovery UDP port (default: 8764)")
    peers_p.add_argument("--timeout", type=float, default=1.5, help="Scan timeout in seconds")
    peers_p.set_defaults(func=handle_session_peers)

    # --- Relay Subcommands ---
    relay_parser = subparsers.add_parser("relay", help="In-Session Live Agent Mesh & Relay")
    relay_subs = relay_parser.add_subparsers(dest="subcommand")

    # server
    srv_p = relay_subs.add_parser("server", help="Start the live relay hub")
    srv_p.add_argument("--host", default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    srv_p.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    srv_p.set_defaults(func=handle_relay_server)

    # peers
    peer_p = relay_subs.add_parser("peers", help="List online agents")
    peer_p.add_argument("--relay", default="ws://localhost:8765/ws", help="Relay WebSocket URL")
    peer_p.set_defaults(func=handle_relay_peers)

    # send
    send_p = relay_subs.add_parser("send", help="Send a message or publish to topic")
    send_p.add_argument("--relay", default="ws://localhost:8765/ws", help="Relay WebSocket URL")
    send_p.add_argument("--sender", help="Sender agent name")
    send_p.add_argument("--topic", help="Topic to publish to")
    send_p.add_argument("--target", help="Specific target agent ID")
    send_p.add_argument("--message", required=True, help="Message text")
    send_p.set_defaults(func=handle_relay_send)

    # rpc
    rpc_p = relay_subs.add_parser("rpc", help="Execute remote RPC on peer agent")
    rpc_p.add_argument("--relay", default="ws://localhost:8765/ws", help="Relay WebSocket URL")
    rpc_p.add_argument("--target", required=True, help="Target agent ID")
    rpc_p.add_argument("--method", required=True, help="Remote method name")
    rpc_p.add_argument("--params", help="JSON string parameters")
    rpc_p.add_argument("--timeout", type=float, default=15.0, help="Timeout in seconds")
    rpc_p.set_defaults(func=handle_relay_rpc)

    # --- Config Subcommand ---
    config_parser = subparsers.add_parser("config", help="Manage agent-comms settings and credentials")
    config_subs = config_parser.add_subparsers(dest="subcommand")

    cfg_show = config_subs.add_parser("show", help="Display full configuration")
    cfg_show.set_defaults(func=handle_config_show)

    cfg_set = config_subs.add_parser("set", help="Set configuration value (e.g. s3.bucket my-bucket)")
    cfg_set.add_argument("key", help="Key path (e.g. default_cloud_provider, s3.bucket, github.token)")
    cfg_set.add_argument("value", help="Value to set")
    cfg_set.set_defaults(func=handle_config_set)

    cfg_get = config_subs.add_parser("get", help="Get configuration value")
    cfg_get.add_argument("key", help="Key path")
    cfg_get.set_defaults(func=handle_config_get)

    # --- Quota Guard Subcommand ---
    quota_parser = subparsers.add_parser("quota", help="AI Provider Rate Limit & Quota Guard")
    quota_subs = quota_parser.add_subparsers(dest="subcommand")

    # status
    q_status = quota_subs.add_parser("status", help="Display quota utilization and rate limit health")
    q_status.add_argument("--provider", help="AI provider (anthropic, openai, gemini, cursor)")
    q_status.set_defaults(func=handle_quota_status)

    # set-budget
    q_budget = quota_subs.add_parser("set-budget", help="Configure quota budget limits for a provider")
    q_budget.add_argument("--provider", required=True, help="AI provider name")
    q_budget.add_argument("--window", choices=["minute", "hour", "day", "week", "month"], default="hour", help="Window duration")
    q_budget.add_argument("--max-requests", type=int, help="Maximum requests in window")
    q_budget.add_argument("--max-tokens", type=int, help="Maximum tokens in window")
    q_budget.set_defaults(func=handle_quota_set_budget)

    # record
    q_rec = quota_subs.add_parser("record", help="Record API usage event")
    q_rec.add_argument("--provider", required=True, help="AI provider name")
    q_rec.add_argument("--tokens", type=int, default=0, help="Tokens consumed")
    q_rec.add_argument("--requests", type=int, default=1, help="Requests consumed")
    q_rec.set_defaults(func=handle_quota_record)

    # evacuate
    q_evac = quota_subs.add_parser("evacuate", help="Preemptively evacuate task into a Context Capsule before rate limit")
    q_evac.add_argument("--task", required=True, help="Task identifier")
    q_evac.add_argument("--provider", required=True, help="Current AI provider approaching limit")
    q_evac.add_argument("--summary", help="Summary of work completed")
    q_evac.add_argument("--next", help="Immediate instructions for next agent/provider")
    q_evac.add_argument("--target", help="Target successor provider (e.g. gemini, openai)")
    q_evac.add_argument("--cloud", help="Push evacuation capsule to cloud provider (s3, gcs, azure, github, relay)")
    q_evac.add_argument("--dir", help="Workspace directory")
    q_evac.set_defaults(func=handle_quota_evacuate)

    # --- MCP Subcommand ---
    mcp_p = subparsers.add_parser("mcp", help="Run Model Context Protocol stdio server")
    mcp_p.add_argument("--dir", help="Workspace root directory")
    mcp_p.set_defaults(func=handle_mcp)

    # --- P2P Mesh Subcommand ---
    p2p_parser = subparsers.add_parser("p2p", help="Peer-to-Peer Dual-Brain mesh tools")
    p2p_subs = p2p_parser.add_subparsers(dest="subcommand")

    template_p = p2p_subs.add_parser("template", help="Scaffold a runnable Dual-Brain starter template")
    template_p.add_argument("--dir", default=".", help="Target directory to create template files")
    template_p.set_defaults(func=handle_p2p_template)

    # --- Setup Subcommand ---
    setup_p = subparsers.add_parser("setup", help="Auto-configure MCP for Claude Desktop, Claude Code, Antigravity, and Cursor")
    setup_p.add_argument("--alias", help="Unique node alias (e.g. providence, code-47, triskelion)")
    setup_p.add_argument("--peers", help="Comma-separated list of known peer aliases")
    setup_p.add_argument("--cloud", choices=["relay", "github", "s3", "gcs", "azure"], default="relay", help="Default cloud capsule provider")
    setup_p.add_argument("--standby", action="store_true", help="Generate/install background standby auto-wake service")
    setup_p.set_defaults(func=handle_setup)

    # --- Demo Subcommand ---
    demo_p = subparsers.add_parser("demo", help="One-command live simulation of Dual-Brain peer collaboration")
    demo_p.set_defaults(func=handle_demo)

    parsed = parser.parse_args()
    if hasattr(parsed, "func"):
        parsed.func(parsed)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

