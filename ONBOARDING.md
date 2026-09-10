# Onboarding Guide: Distributed Agent Mesh & Dual-Brain Collaboration

Welcome to **Agent Comms**! This guide gets you up and running with multi-machine agent collaboration in **under 5 minutes**.

Whether you want **two agents on different computers acting as one unified mind** (Peer-to-Peer Dual-Brain), or **frictionless session handoff** across laptops and cloud workstations (Context Capsules), this guide provides copy-pasteable recipes and architectural patterns.

> 💡 **Prefer to just chat with your AI in plain English?**  
> If you don't want to run CLI commands, check out the [**Natural Language User Guide (`USER_GUIDE.md`)**](USER_GUIDE.md) for everyday prompt cheat sheets for Claude Desktop, Antigravity, and Cursor.

---

## ⚡ 1-Command Automated Installation

You don't need to clone repositories or manually configure JSON files. Run **one command** for your operating system:

### Option A: macOS & Linux (Terminal)
```bash
curl -sSL https://raw.githubusercontent.com/BlahBlah23406/agent-comms/master/install.sh | bash
```

### Option B: Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/BlahBlah23406/agent-comms/master/install.ps1 | iex
```

### Option C: Any System with Pip
```bash
pip install git+https://github.com/BlahBlah23406/agent-comms.git && agent-comms setup
```

**What this one command does automatically:**
1. Installs the `agent-comms` Python package and registers the global `agent-comms` CLI.
2. Auto-detects **Claude Desktop** and injects the MCP configuration into `claude_desktop_config.json`.
3. Auto-detects **Antigravity (`agy` & IDE)** and injects the MCP configuration into `mcp_config.json`.
4. Auto-detects **Cursor** and injects the MCP configuration.
5. Initializes local Context Capsule storage at `~/.agent-comms/capsules/`.

---

## 🎮 1-Command Live Demo

Want to see two agents act as one mind in your terminal right now?
```bash
agent-comms demo
```
This boots an in-process relay, spawns Node Alpha and Node Beta, negotiates a contract, exchanges real-time cognitive deltas, and saves twin Context Capsules in 2 seconds!

---

## 🚀 2-Minute Custom Mesh Quickstart

### 1. Scaffold a Dual-Brain Starter Template
Run the built-in scaffolding command to create runnable peer templates:
```bash
agent-comms p2p template --dir ./my-dual-brain
cd my-dual-brain
```

This generates:
* `peer_alpha.py` (Left Hemisphere)
* `peer_beta.py` (Right Hemisphere)
* `quickstart.py`

### 3. Run the Dual-Brain Mesh
Open two terminal windows:

**Terminal 1 (Start the Relay Hub):**
```bash
agent-comms relay server --port 8765
```

**Terminal 2 (Start Node Alpha):**
```bash
python peer_alpha.py
```

**Terminal 3 (Start Node Beta):**
```bash
python peer_beta.py
```

**What you will see:**
1. Node Alpha and Node Beta discover each other in real-time.
2. Alpha asserts an initial domain belief (`system_mode = high_throughput`).
3. Beta immediately absorbs this belief and symmetrically proposes a contract.
4. Beta discovers an optimization and broadcasts a **Cognitive Delta**.
5. Alpha mutates its live runtime pipeline **on the fly without restarting**!
6. Both peers persist synchronized twin Context Capsules.

---

## ⚡ Core Concepts: In 10 Lines of Python

The high-level `DualBrainNode` API gives you instant access to peer discovery, replicated mental models, and out-of-session persistence:

```python
import asyncio
from agent_comms.mesh import DualBrainNode

async def main():
    # 1. Connect to the mesh
    async with DualBrainNode(agent_id="node-alpha", relay_url="ws://localhost:8765/ws") as node:
        
        # 2. Assert a shared fact or belief into the replicated blackboard
        await node.set_belief("target_version", "v2.0", rationale="Migration approved")
        
        # 3. Listen for cognitive deltas from peer agents across the network
        @node.on_belief_update
        async def on_delta(key, value, rationale):
            print(f"Peer updated {key} -> {value} ({rationale})")

        # 4. Symmetrically negotiate an interface contract
        await node.propose_contract("data_contract", {"batch_id": "int", "status": "str"})

        # 5. Export a synchronized Context Capsule for out-of-session handoff
        capsule = node.export_twin_capsule("TASK-101", summary="Phase 1 complete")
        print("Persisted Context Capsule:", capsule.capsule_id)

asyncio.run(main())
```

---

## 🌐 5-Minute Cross-Machine Setup

Connecting two physical machines across the internet (e.g., your Windows/Mac laptop and a remote Linux GPU or cloud server) is just as simple.

```
┌──────────────────────────────────────┐            ┌──────────────────────────────────────┐
│        Laptop (Windows / macOS)      │            │        Cloud Node (Ubuntu Linux)     │
│        [Node Alpha - Left Brain]     │            │        [Node Beta - Right Brain]     │
│                                      │            │                                      │
│  - Ingest & Verification             │            │  - High-throughput GPU Compute       │
│  - Local Workspace State             │            │  - Kernel Telemetry Harvesting       │
└──────────────────┬───────────────────┘            └──────────────────▲───────────────────┘
                   │                                                   │
                   └────────────────[ AHRP Relay Mesh ]────────────────┘
                             (Tailscale / VPN / Public IP:8765)
```

### Step 1: Start the Relay Broker on the Host Machine
Run the relay server on any node with network visibility (e.g., your Linux server with IP `100.118.132.56` or `my-server.tailscale.net`):
```bash
agent-comms relay server --host 0.0.0.0 --port 8765
```

### Step 2: Configure Node Alpha (Laptop)
In `peer_alpha.py`, point the `relay_url` to your server's IP:
```python
RELAY_URL = "ws://100.118.132.56:8765/ws"
node = DualBrainNode(agent_id="node-laptop", relay_url=RELAY_URL, role="planner")
```

### Step 3: Configure Node Beta (Cloud)
In `peer_beta.py` on your cloud server:
```python
RELAY_URL = "ws://localhost:8765/ws" # Local to relay host
node = DualBrainNode(agent_id="node-cloud", relay_url=RELAY_URL, role="worker")
```

Run both! The two agents are now acting as **one mind across two physical computers**.

---

## 📦 Out-of-Session Handoff (Context Capsules)

When you need to pause work on your laptop and resume later on another machine without context window bloat:

### 1. Package Your Current State & Mental Model
```bash
agent-comms capsule pack \
  --task "AUTH-01" \
  --summary "Refactored JWT authentication handler" \
  --next "Execute pytest tests/test_auth.py" \
  --learning "finding:PyJWT requires algorithms=['HS256']" \
  --learning "gotcha:Token expiry must use UTC timestamps"
```

This creates a self-contained capsule (`.json`) containing:
* Your exact Git diff (staged and unstaged)
* Any untracked files
* Epistemic learnings (findings, gotchas, rejected hypotheses)
* Immediate next actions

### 2. Resume on Machine B
Transfer the capsule file or let your sync storage sync it, then unpack:
```bash
agent-comms capsule unpack "AUTH-01"
```

The Git patch and untracked files are automatically applied, and an optimized briefing prompt is generated for the incoming AI agent.

---

## 🔌 Connecting with AI Assistants & Frameworks

### 1. Antigravity CLI (`agy`) & IDE
Run the MCP server to give Antigravity direct access to capsule operations:
```bash
agent-comms mcp
```
Configure in Antigravity's MCP settings:
```json
{
  "mcpServers": {
    "agent-comms": {
      "command": "python",
      "args": ["-m", "agent_comms.cli", "mcp"]
    }
  }
}
```

### 2. Claude Desktop, Cursor, and Windsurf
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "agent-comms": {
      "command": "agent-comms",
      "args": ["mcp"]
    }
  }
}
```

---

## 📚 Real-World Verification Archives

This protocol has been battle-tested on real physical hardware across the internet:
* [Experiment 1: Orchestrator / Worker Live Collaboration](docs/experiments/01_ORCHESTRATOR_WORKER_EXPERIMENT.md) (Windows 11 <-> Oracle Cloud Ubuntu Linux).
* [Experiment 2: Peer-to-Peer Dual-Brain Distributed Pipeline](docs/experiments/02_PEER_TO_PEER_DUAL_BRAIN_EXPERIMENT.md) (Multi-server cryptographic Merkle ring with dynamic cognitive adaptation).
* [Archived Experiment Code](docs/experiments/code/).

---

## 🛠️ CLI Command Reference Cheat Sheet

| Command | Purpose |
| :--- | :--- |
| `agent-comms p2p template [--dir DIR]` | Scaffolds a runnable Dual-Brain starter template |
| `agent-comms relay server [--port 8765]` | Starts the AHRP WebSocket real-time broker |
| `agent-comms relay peers [--relay URL]` | Lists all active connected agents and capabilities |
| `agent-comms capsule pack --task ID ...` | Packages Git diffs, untracked files, and mental model |
| `agent-comms capsule unpack <ID or Path>` | Restores working directory and displays agent briefing |
| `agent-comms capsule list` | Lists all saved Context Capsules |
| `agent-comms mcp` | Launches the Model Context Protocol stdio server |
