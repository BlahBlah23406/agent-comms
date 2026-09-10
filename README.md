# Agent Comms: Universal Agent Handover & Live Relay Suite

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)]()
[![Protocol](https://img.shields.io/badge/protocol-AHRP%20v1.0-orange.svg)]()

**Agent Comms** is a comprehensive, production-grade protocol and toolkit enabling AI coding agents to communicate, share work, and transfer mental models across different sessions and physical computers.

It supports both:
1. **Out-of-Session Handoff (Context Capsules):** Package an agent's epistemic discoveries, task roadmap, git diffs, and untracked files into a structured, portable capsule to resume seamlessly on another computer or future session without context window bloat.
2. **In-Session Live Collaboration (AHRP Relay):** A real-time WebSocket event mesh enabling distributed agents on separate machines to discover peers, broadcast milestones via Pub/Sub, and execute cross-machine Remote Procedure Calls (RPC).

---

## Architecture Overview

```
                      IN-SESSION (Live)             OUT-OF-SESSION (Persistent)
               ┌───────────────────────────────┬────────────────────────────────┐
               │ - Local sockets / IPC         │ - Local files / SQLite         │
SAME MACHINE   │ - Event emitters / In-memory  │ - Antigravity Brain logs       │
               │ - Subagent pools              │ - Git working directories      │
               ├───────────────────────────────┼────────────────────────────────┤
               │ - AHRP WebSocket Relay        │ - AHRP Context Capsules        │
CROSS-MACHINE  │ - Peer Discovery & RPC        │ - Git Diffs & Untracked Files  │
               │ - Live Topic Pub/Sub Mesh     │ - Epistemic Learnings Taxonomy │
               └───────────────────────────────┴────────────────────────────────┘
```

```
┌──────────────────────────────────────┐            ┌──────────────────────────────────────┐
│        Machine A (e.g. Laptop)       │            │       Machine B (e.g. Workstation)   │
│ ┌──────────────────────────────────┐ │            │ ┌──────────────────────────────────┐ │
│ │   Agent A (Antigravity / Claude) │ │            │ │   Agent B (Same or Peer Agent)   │ │
│ └─────────────────┬────────────────┘ │            │ └──────────────────▲───────────────┘ │
│                   │                  │            │                    │                 │
│         [Context Capsule Export]     │            │         [Context Capsule Import]     │
│                   │                  │            │                    │                 │
│                   ▼                  │            │                    │                 │
│       ~/.agent-comms/capsules/ ──────┼──[Sync/S3/Git]───► ~/.agent-comms/capsules/       │
│                                      │            │                                      │
│       [AHRP Relay Client] ───────────┼──[Live WS]─┼──────► [AHRP Relay Client]           │
│         - Pub/Sub milestones         │   Broker   │          - Execute remote tasks      │
│         - Direct RPC invocation      │            │          - Stream execution logs     │
└──────────────────────────────────────┘            └──────────────────────────────────────┘
```

---

## Key Features

- **Context Capsule Engine:**
  - Standardized JSON Schema preserving task progression and epistemic learnings (findings, rejected hypotheses, gotchas).
  - Captures Git unified diffs (staged and unstaged) and untracked files without polluting commit history.
  - Automatically synthesizes token-efficient Markdown briefings tailored for incoming agent prompts.
- **In-Session Live Relay Hub:**
  - High-performance FastAPI + WebSocket message broker.
  - Topic-based Publish/Subscribe (`pipeline.progress`, `alerts`).
  - Correlated point-to-point Remote Procedure Calls (RPC).
  - Automatic peer discovery with capability advertising (`gpu_acceleration`, `docker_runner`).
- **Model Context Protocol (MCP) Server:**
  - Exposes `export_handoff_capsule`, `import_handoff_capsule`, and `list_saved_capsules` as native MCP tools for Antigravity, Claude Desktop, Cursor, and Windsurf.
- **Unified CLI (`agent-comms`):**
  - Instant command-line tools for packaging, inspecting, and resuming capsules, as well as testing live relays and querying online peers.

---

## Directory Structure

```
agent-comms/
├── README.md                      # Project overview & architecture
├── ONBOARDING.md                  # 5-minute quickstart & developer onboarding
├── RESEARCH_AND_COMPARISON.md     # In-depth industry research and taxonomy
├── SPECIFICATION.md               # Formal protocol and schema specification
├── TUTORIAL.md                    # Hands-on walkthroughs and examples
├── requirements.txt               # Dependencies
├── setup.py                       # Installable package setup
├── agent_comms/                   # Core Python package
│   ├── models/                    # Pydantic data models
│   │   ├── capsule.py             # ContextCapsule, TaskGraph, EpistemicLearning
│   │   └── protocol.py            # RelayFrame, AgentDescriptor, FrameType
│   ├── mesh/                      # Peer-to-Peer Dual-Brain mesh engine
│   │   ├── blackboard.py          # Replicated CognitiveBlackboard & deltas
│   │   └── node.py                # High-level DualBrainNode agent interface
│   ├── capsule/                   # Out-of-session handoff engine
│   │   ├── git_sync.py            # Git diff, untracked files, patch application
│   │   ├── packager.py            # Capsule creation and briefing generation
│   │   ├── unpacker.py            # Patch restoration and briefing injection
│   │   └── store.py               # Local and remote capsule storage
│   ├── relay/                     # In-session real-time message broker
│   │   ├── server.py              # FastAPI + WebSocket hub
│   │   └── client.py              # Asynchronous AgentRelayClient (RPC & Pub/Sub)
│   ├── mcp/                       # Model Context Protocol adapter
│   │   └── server.py              # JSON-RPC MCP server
│   └── cli.py                     # CLI entrypoint (`agent-comms`)
├── docs/                          # Documentation & historical archives
│   └── experiments/               # Full reports & code from multi-machine tests
│       ├── README.md              # Index of real-world experiments
│       ├── 01_ORCHESTRATOR_WORKER_EXPERIMENT.md
│       ├── 02_PEER_TO_PEER_DUAL_BRAIN_EXPERIMENT.md
│       └── code/                  # Exact reproducible scripts
└── tests/                         # Test and verification suite
    ├── test_capsule.py            # Unit tests for serialization & briefing
    ├── test_relay.py              # Tests for live relay, pub/sub, RPC
    ├── test_mesh.py               # Tests for Dual-Brain cognitive sync & twin capsules
    ├── scenario_out_of_session.py # End-to-end multi-machine handoff simulation
    ├── scenario_in_session_live.py# End-to-end live peer RPC & stream simulation
    └── run_all.py                 # Master test runner
```

---

## Real-World Multi-Machine Validations

This protocol and architecture have been validated across physical, heterogeneous machines (`Providence` on Windows 11 and `code-47` on Oracle Cloud Ubuntu Linux via Tailscale):

### 1. Peer-to-Peer Dual-Brain Architecture ("Two Computers, One Mind")
- **Multi-Server Pipeline Ring**: Ingest & verification service on Windows (`:9201`) + Numerical transform & Merkle engine on Linux (`:9202`). Neither computer could run the pipeline alone.
- **Symmetric Interface Negotiation**: Co-equal agents negotiated and locked contracts via consensus in `<1s`.
- **Replicated Cognitive Blackboard**: Shared mental models where cognitive deltas broadcast in real time.
- **Live Dynamic Adaptation**: When the Linux peer discovered vector presorting improved CPU branch prediction, it asserted a cognitive delta. The Windows peer **dynamically adapted its generator on the fly without restarting services**.
- **Twin Context Capsules**: Synchronized out-of-session handoff records saved on both nodes.
- Full report and logs: [`docs/experiments/02_PEER_TO_PEER_DUAL_BRAIN_EXPERIMENT.md`](docs/experiments/02_PEER_TO_PEER_DUAL_BRAIN_EXPERIMENT.md).

### 2. Orchestrator / Worker Live Collaboration
- Real-time planning channel on `channel.planning`.
- Live remote task invocation: Windows coordinator dynamically invoked Linux workers to harvest live kernel telemetry (`/proc/loadavg`, `/proc/meminfo`, `/proc/net/tcp`) via RPC.
- Full report and logs: [`docs/experiments/01_ORCHESTRATOR_WORKER_EXPERIMENT.md`](docs/experiments/01_ORCHESTRATOR_WORKER_EXPERIMENT.md).

### 3. 3-Way Tri-Brain Distributed Mesh ("Three OSs, Three Machines, One Mind")
- **Heterogeneous Tri-Mesh**: `Providence` (Windows 11) + `The-Triskelion` (macOS Apple Silicon ARM64) + `code-47` (Ubuntu Linux 24.04 OCI).
- **Full Mesh Cognitive Synchronization**: Symmetrically locked `TRI_BRAIN_CONSENSUS_V1` and propagated cognitive deltas across all 3 operating systems simultaneously.
- **Hardware-Specific Deliberation**: Apple Silicon Metal/Neural engine policies asserted from macOS, cloud kernel telemetry asserted from Linux, ledger coordination from Windows.
- **Synchronized Tri-Brain Persistence**: All 3 nodes exported twin Context Capsules with 100% consensus.
- Full report and logs: [`docs/experiments/03_THREE_WAY_TRI_BRAIN_EXPERIMENT.md`](docs/experiments/03_THREE_WAY_TRI_BRAIN_EXPERIMENT.md).

---

## Quickstart

For full step-by-step onboarding, see the [**Onboarding Guide (`ONBOARDING.md`)**](ONBOARDING.md).

### 1. Scaffold a Dual-Brain Template
```bash
agent-comms p2p template --dir ./my-mesh
```

### 2. Run the Verification Suite
Execute the entire test suite and multi-machine simulations:

```bash
python tests/run_all.py
```

### 3. Start the Live Relay Hub (In-Session)
```bash
agent-comms relay server --host 0.0.0.0 --port 8765
```

### 4. Package a Handoff (Out-of-Session)
```bash
agent-comms capsule pack \
  --task "AUTH-01" \
  --summary "Migrated auth module to JWT; integration test pending" \
  --next "Run python -m unittest tests/test_auth.py" \
  --learning "finding:PyJWT requires algorithms=['HS256']" \
  --learning "rejected:Cookie storage rejected due to CORS policy"
```

### 5. Resume on Another Machine
```bash
agent-comms capsule unpack "AUTH-01"
```

---

## Further Reading
- [**Onboarding Guide** (`ONBOARDING.md`)](ONBOARDING.md) — 5-minute setup and recipes for dual-brain agents.
- [**Research & Architectural Comparison** (`RESEARCH_AND_COMPARISON.md`)](RESEARCH_AND_COMPARISON.md) — Comparison against AutoGen, LangGraph, Temporal, and MCP.
- [**Protocol Specification** (`SPECIFICATION.md`)](SPECIFICATION.md) — Formal AHRP protocol and frame schemas.
- [**Tutorial & Recipes** (`TUTORIAL.md`)](TUTORIAL.md) — Hands-on scenarios and developer patterns.
- [**Experiment Archives** (`docs/experiments/`)](docs/experiments/) — Detailed test reports from live internet runs.
