# Agent Comms

[![Tests](https://github.com/BlahBlah23406/agent-comms/actions/workflows/tests.yml/badge.svg)](https://github.com/BlahBlah23406/agent-comms/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](setup.py)
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

### 3. Cloud Capsule Synchronization (Zero Extra Infra)
Save capsules to your preferred cloud provider (S3, GCS, Azure, GitHub Gists, or Relay) and pull from any machine:
```bash
# Push capsule to GitHub Gist or AWS S3
agent-comms capsule push "AUTH-01" --cloud github
# or
agent-comms capsule push "AUTH-01" --cloud s3

# Pull and immediately apply patch on another machine
agent-comms capsule pull "AUTH-01" --cloud github --apply
```

### 4. 1-Command Active Cross-Session (Instant Auto-Wake)
Work from one machine and activate the rest with zero manual network setup:
- **On secondary machine (e.g. Desktop / Cloud GPU rig):**
  ```bash
  agent-comms standby
  ```
- **On primary machine (e.g. Laptop):**
  ```bash
  agent-comms session start --target desktop --capsule "AUTH-01"
  ```
*Machine A automatically discovers Machine B over LAN, sends a wake-up signal, transmits the workspace capsule, and links both into an active real-time cross-session.*

### 5. Preemptive AI Rate-Limit & Quota Guard
Never lose your work or get stuck mid-task due to AI provider quota exhaustion or rate limits (hourly, daily, weekly, or request token buckets). Agent Comms detects approaching rate limits and automatically evacuates your session into a handoff Context Capsule right before a 429 lockout:
```bash
# Check current AI provider quota usage & remaining headroom
agent-comms quota status --provider anthropic

# Set a safety budget (e.g. 50 requests/min, or 100,000 tokens/hr)
agent-comms quota set-budget --provider anthropic --requests 50 --window hour

# Preemptively evacuate session before rate limit lockout
agent-comms quota evacuate --task "AUTH-01" --target gemini
```
*Your uncommitted files, diffs, and immediate next steps are preserved, allowing a successor provider (e.g. Gemini, OpenAI) or another machine to pick up where you left off with zero context loss.*

### 6. Multi-Machine Node Setup (`--alias`)
Set up any machine in 1 command and automatically link it to your peer network:
```bash
# On primary laptop:
agent-comms setup --alias laptop --peers laptop,desktop-gpu,cloud-node

# On secondary/remote machine (with auto-wake background standby service):
agent-comms setup --alias desktop-gpu --peers laptop,desktop-gpu,cloud-node --standby
```
Configures MCP and global guidelines automatically across:
- **Claude Code CLI** (`~/.claude.json` & `claude mcp add`)
- **Antigravity (AGY)** (`mcp_config.json` & `agy mcp add`)
- **Claude Desktop** (`claude_desktop_config.json`)
- **Cursor** (`mcp.json`)

### 7. Run the Live Collaboration Demo
See two local agents discover each other and collaborate:
```bash
agent-comms demo
```

### 8. Use in Claude Desktop, Claude Code, Antigravity, or Cursor (MCP)
Agent Comms includes full MCP tooling for Context Capsules, Cloud Storage, Active Cross-Sessions, and Quota Protection:
- `export_handoff_capsule` (with optional cloud push)
- `import_handoff_capsule` (with automatic cloud fallback)
- `push_handoff_capsule` & `pull_handoff_capsule` & `list_cloud_capsules`
- `start_cross_session` & `scan_network_peers`
- `check_quota_status`, `record_usage_and_guard`, & `preemptive_quota_evacuate`

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
> *"Start an active cross-session with desktop-gpu for task PERF-99."*  
> *"Check our quota status and evacuate to Gemini if we are close to Claude's rate limit."*

---

## Documentation

- [**Natural Language User Guide** (`USER_GUIDE.md`)](USER_GUIDE.md) — Plain-English prompt examples for Claude Desktop, Claude Code, Antigravity, and Cursor.
- [**Onboarding Guide** (`ONBOARDING.md`)](ONBOARDING.md) — Step-by-step developer onboarding and distributed agent recipes.
- [**Protocol Specification** (`SPECIFICATION.md`)](SPECIFICATION.md) — Formal AHRP wire protocol and JSON schemas.
- [**Tutorial & Recipes** (`TUTORIAL.md`)](TUTORIAL.md) — Hands-on walkthroughs and implementation examples.
