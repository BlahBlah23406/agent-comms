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
├── RESEARCH_AND_COMPARISON.md     # In-depth industry research and taxonomy
├── SPECIFICATION.md               # Formal protocol and schema specification
├── TUTORIAL.md                    # Hands-on walkthroughs and examples
├── requirements.txt               # Dependencies
├── setup.py                       # Installable package setup
├── agent_comms/                   # Core Python package
│   ├── models/                    # Pydantic data models
│   │   ├── capsule.py             # ContextCapsule, TaskGraph, EpistemicLearning
│   │   └── protocol.py            # RelayFrame, AgentDescriptor, FrameType
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
└── tests/                         # Test and verification suite
    ├── test_capsule.py            # Unit tests for serialization & briefing
    ├── test_relay.py              # Tests for live relay, pub/sub, RPC
    ├── scenario_out_of_session.py # End-to-end multi-machine handoff simulation
    ├── scenario_in_session_live.py# End-to-end live peer RPC & stream simulation
    └── run_all.py                 # Master test runner
```

---

## Quickstart

### 1. Run the Verification Suite
Execute the entire test suite and multi-machine simulations:

```bash
cd C:\Users\shaya\agent-comms
python tests/run_all.py
```

### 2. Package a Handoff (Out-of-Session)
```bash
agent-comms capsule pack \
  --task "AUTH-01" \
  --summary "Migrated auth module to JWT; integration test pending" \
  --next "Run python -m unittest tests/test_auth.py" \
  --learning "finding:PyJWT requires algorithms=['HS256']" \
  --learning "rejected:Cookie storage rejected due to CORS policy"
```

### 3. Resume on Another Machine
```bash
agent-comms capsule unpack "AUTH-01"
```

### 4. Start the Live Relay Hub (In-Session)
```bash
agent-comms relay server --host 0.0.0.0 --port 8765
```

---

## Further Reading
- For deep architectural comparisons with AutoGen, LangGraph, Temporal, and MCP, see [`RESEARCH_AND_COMPARISON.md`](RESEARCH_AND_COMPARISON.md).
- For formal JSON schemas and protocol frame definitions, see [`SPECIFICATION.md`](SPECIFICATION.md).
- For end-to-end user workflows, see [`TUTORIAL.md`](TUTORIAL.md).
