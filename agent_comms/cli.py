"""
Agent Communication Suite CLI
=============================
Unified command-line interface for Context Capsules, Live Relay, and MCP integration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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


def handle_relay_server(args):
    print(f"[+] Starting AHRP Relay Server on {args.host}:{args.port}...")
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


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

    # list
    list_p = capsule_subs.add_parser("list", help="List stored capsules")
    list_p.add_argument("--store", help="Custom capsule store directory")
    list_p.set_defaults(func=handle_capsule_list)

    # show
    show_p = capsule_subs.add_parser("show", help="Display capsule markdown briefing")
    show_p.add_argument("capsule", help="Capsule ID or file path")
    show_p.add_argument("--store", help="Custom capsule store directory")
    show_p.set_defaults(func=handle_capsule_show)

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

    parsed = parser.parse_args()
    if hasattr(parsed, "func"):
        parsed.func(parsed)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
