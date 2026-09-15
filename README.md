# Agent Comms

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

> A lightweight protocol and toolkit for AI coding agents to share context, hand off tasks across sessions, and collaborate in real-time across machines.

---

## What It Is

When working with AI coding agents (Claude Desktop, Antigravity, Cursor, etc.), two major challenges arise:
1. **Context Loss Across Sessions:** Starting a new chat or moving to another machine resets the agent's mental model and working memory.
2. **Multi-Agent Coordination:** Agents running in different environments or physical computers cannot easily communicate, exchange state, or run coordinated tasks.

**Agent Comms** provides a unified solution:
- **Context Capsules (Out-of-Session Handoff):** Packages an agent's task roadmap, architectural decisions, rejected hypotheses, and uncommitted git diffs into a compact, portable bundle. The next agent session resumes immediately without burning context tokens.
- **AHRP Live Relay (In-Session Collaboration):** A real-time WebSocket mesh supporting peer discovery, publish/subscribe messaging, and cross-machine Remote Procedure Calls (RPC).
- **Native MCP Integration:** Works out-of-the-box with Claude Desktop, Antigravity, and Cursor via the Model Context Protocol.

---

## How It Works

### 1. Out-of-Session Handoff (Context Capsules)
Agent Comms captures cognitive state alongside your working tree without polluting Git commit history:
- **State & Decisions:** Records what worked, what was rejected, and the immediate next steps.
- **Code Diffs:** Captures staged, unstaged, and untracked changes into a clean patch.
- **Briefing Generation:** Produces a token-efficient Markdown briefing tailored for the incoming agent.

```
Machine A (Active Session)                  Machine B (New Session)
 ┌──────────────────────────┐                ┌──────────────────────────┐
 │ Agent exports capsule    │──[File/Sync]──▶│ Agent imports capsule    │
 │ (diffs + state + roadmap)│                │ (restores diffs + state) │
 └──────────────────────────┘                └──────────────────────────┘
```

### 2. In-Session Collaboration (Live Relay Mesh)
For multi-agent workflows, a lightweight relay server coordinates agents over WebSockets:
- **Peer Discovery:** Agents announce presence, roles, and hardware capabilities.
- **Cognitive Blackboard:** Replicated state where agents share real-time decisions and learnings.
- **Direct RPC:** Agents can invoke tools or run commands on peer machines.

---

## How to Get It

### Installation

**Using Pip:**
```bash
pip install git+https://github.com/BlahBlah23406/agent-comms.git
```

**Or Clone & Install Locally:**
```bash
git clone https://github.com/BlahBlah23406/agent-comms.git
cd agent-comms
pip install -e .
```

**One-Line Install Script:**
- **macOS / Linux:**
  ```bash
  curl -sSL https://raw.githubusercontent.com/BlahBlah23406/agent-comms/master/install.sh | bash
  ```
- **Windows (PowerShell):**
  ```powershell
  irm https://raw.githubusercontent.com/BlahBlah23406/agent-comms/master/install.ps1 | iex
  ```

Run initial setup:
```bash
agent-comms setup
```

---

## Quick Usage

### 1. Save Progress (Create a Capsule)
Before ending a session or switching computers:
```bash
agent-comms capsule pack \
  --task "AUTH-01" \
  --summary "Migrated auth module to JWT; integration test pending" \
  --next "Run pytest tests/test_auth.py" \
  --learning "finding:PyJWT requires algorithms=['HS256']"
```

### 2. Resume on Another Machine
Restore your uncommitted files and task briefing:
```bash
agent-comms capsule unpack "AUTH-01"
```

### 3. Run the Live Collaboration Demo
See two local agents discover each other and collaborate:
```bash
agent-comms demo
```

### 4. Use in Claude Desktop, Antigravity, or Cursor (MCP)
Agent Comms includes an MCP server exposing `export_handoff_capsule`, `import_handoff_capsule`, and `list_saved_capsules`.

Add to your MCP settings file:
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

Once added, interact naturally with your agent:
> *"Save my progress into a handoff capsule for task AUTH-01."*  
> *"Resume task AUTH-01 from my latest capsule."*

---

## Documentation

- [**Natural Language User Guide** (`USER_GUIDE.md`)](USER_GUIDE.md) — Plain-English prompt examples for Claude Desktop, Antigravity, and Cursor.
- [**Onboarding Guide** (`ONBOARDING.md`)](ONBOARDING.md) — Step-by-step developer onboarding and distributed agent recipes.
- [**Protocol Specification** (`SPECIFICATION.md`)](SPECIFICATION.md) — Formal AHRP wire protocol and JSON schemas.
- [**Tutorial & Recipes** (`TUTORIAL.md`)](TUTORIAL.md) — Hands-on walkthroughs and implementation examples.
