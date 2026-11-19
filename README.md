# Agent Comms

[![Tests](https://github.com/BlahBlah23406/agent-comms/actions/workflows/tests.yml/badge.svg)](https://github.com/BlahBlah23406/agent-comms/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](setup.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

> A lightweight protocol and toolkit for AI coding agents to share context, hand off tasks across sessions, and collaborate in real-time across machines.

![Agent Comms Demo](demo.gif)

---

## TL;DR

`agent-comms` is a plugin for the terminal AI agents you already use (Claude Code, Codex, Antigravity CLI/agy). It does two things automatically:
1. Saves your work every other turn so you can switch to any other agent or machine and say "continue".
2. Spreads big tasks across all your agent CLIs (and SSH machines) so no single subscription runs out.

---

## Quick Start (3 steps)

1. Install the package:
```bash
pip install git+https://github.com/BlahBlah23406/agent-comms.git
```

2. Run setup to install the hooks, MCP server, and instructions into your agents:
```bash
agent-comms setup --alias <name>
```

3. (Optional) Point to a storage server so other machines see your saves:
```bash
agent-comms config set storage_server_url http://<server>:8765
agent-comms config set auto_sync_storage true
```

---

## Switching Agents (Autosave)

After setup, a hook saves a capsule of your chat every 2 turns. During long turns, a hook runs after each tool call and saves every 10 minutes in the background. It also saves right away when Codex reaches 90% of its 5-hour or weekly limit, when Claude Code shows its usage-limit grace warning, or when any agent shows a usage-limit message. To change the Codex threshold, run `agent-comms config set save_at_percent 85`.

Codex asks you to trust new hooks once; open `codex` and approve the agent-comms hooks or they won't run.

To pick up where you left off in any agent, just say `continue` (which calls the `resume_latest` MCP tool) or run:
```bash
agent-comms resume
```

On a different machine, add `--apply` to also bring the uncommitted code changes over:
```bash
agent-comms resume --apply
```

To change how often the hook saves (for example, every 3 turns):
```bash
agent-comms config set autosave_every 3
```

---

## Sharing Work Across Agents

For big tasks, helpers do most of the work. The agent you talk to plans the work, hands it out, reviews the results, and runs the final tests. Helpers can't hand their tasks on. When possible, each task goes to a different provider, and the agent asking for help uses its own provider last so one subscription doesn't pay for everything. It balances work across providers using minutes worked in the last 5 hours as a stand-in for tokens. A usage-limit message like "session limit" rests that agent for an hour and moves the task to another agent. Agents whose sandbox can't start or that aren't logged in on a machine rest 6 hours, and `agent-comms agents` shows why. If a machine can't be reached over SSH, only that machine rests 5 minutes. If every agent tried fails, the failed task lists what each agent hit.

See available agents and their runs and minutes worked in the last 5 hours.
```bash
agent-comms agents
```

Hand tasks to other agents in the background (or add `--wait` to wait for results):
```bash
agent-comms run "task one" "task two"
```
Use `--agent <slot>` (or `agent` in `run_on_agents`) to pick who goes first; naming your own provider is ignored while other providers are free, and it still moves on to another agent if that one fails.

Check background jobs or read the output of one job:
```bash
agent-comms jobs
agent-comms jobs <id>
```

Inside an agent chat, the agent can use the MCP tools `save_progress`, `run_on_agents`, `check_jobs`, `agent_status`, and `resume_latest` to do the same work. For Codex, the installer adds `env_vars = ["SSH_AUTH_SOCK"]` and `tool_timeout_sec = 900` to the `agent-comms` MCP server entry.

**Permissions:** By default, helpers run in each CLI's auto mode: `claude --permission-mode auto`, `agy --mode auto`, or Codex's `workspace-write` sandbox (with network access enabled for Codex helpers). They can run builds and tests while risky actions are still checked. Set `fleet_permissions` to `full` to skip all checks for all helpers:
```bash
agent-comms config set fleet_permissions full
```
Or use `fleet_full_agents` to skip all checks for only the providers you list, or add a per-host `full_agents` list inside `fleet_hosts` to run those agents without permission checks on that host only. Only enable these settings in projects you trust.

**Ollama:** By default, the helper list is `claude`, `codex`, `agy`. Local or cloud Ollama models are only used when you add `ollama` to the agent list:
```bash
agent-comms config set fleet_agents '["claude","codex","agy","ollama"]'
agent-comms config set ollama_model <model>
```

**SSH machines:** You can add other computers that you can reach over SSH:
```bash
agent-comms fleet add-host my-server --ssh me@192.168.1.20 --dir ~/myproject --agents claude,codex
```
Add `--powershell` if the remote machine runs Windows. Remove a host with `agent-comms fleet remove-host <name>`.

Helpers on other machines start from your project's current state in a throwaway copy. Machines without a copy of the project get a snapshot of it (tracked and new files, up to 50 MB). Their file changes come back as a patch and are applied to your project automatically. If a patch cannot be applied, it is saved for you to check.

Each machine's CLIs must be logged in for SSH use too; on macOS the keychain is locked over SSH, so use `claude setup-token` and set `CLAUDE_CODE_OAUTH_TOKEN`.

**Busy machines say no:** before a machine takes a helper job, it checks itself. Busy counts helper jobs running on that machine (agent apps and open chats don't count). If it is too busy, the job goes to another agent and that machine is skipped for 10 minutes. See how a machine is doing with:
```bash
agent-comms busy
```
Change the limits on each machine (these are the defaults):
```bash
agent-comms config set cap_cpu_percent 85      # too busy above this CPU use
agent-comms config set cap_min_free_mb 1024    # too busy below this much free memory
agent-comms config set cap_running_agents 4    # too busy when this many helper jobs are running on this machine
agent-comms config set accept_work false       # never take helper jobs (set to true to turn back on)
```

Note: Kaggle and other remote GPU services are not supported yet.

---

## Chat Apps (Claude Desktop, Gemini app, ChatGPT)

Chat apps have no hooks, so run `agent-comms instructions` and paste the text into the app's custom instructions. Then the app calls the `save_progress` MCP tool every second reply and `resume_latest` when you say `continue`, and can hand coding work to agents with `run_on_agents` (with `folder` set). Use the same project name as the code folder so chat apps and coding agents share saves.

Setup adds the MCP server to Claude Desktop automatically. In the Gemini Mac app, add it under connector settings as a local MCP server with command `agent-comms` and argument `mcp`. ChatGPT only accepts remote HTTPS MCP connectors, so it is not connected yet; for now, paste the output of `agent-comms resume` into ChatGPT to continue there.

---

## What It Is

When working with AI coding agents (Claude Desktop, Antigravity, Cursor, OpenClaw, etc.), two major challenges arise:
1. **Context Loss Across Sessions:** Starting a new chat or moving to another machine resets the agent's mental model and working memory.
2. **Multi-Agent Coordination:** Agents running in different environments or physical computers cannot easily communicate, exchange state, or run coordinated tasks.

**Agent Comms** provides a unified solution:
- **Context Capsules (Out-of-Session Handoff):** Packages an agent's task roadmap, architectural decisions, rejected hypotheses, and uncommitted git diffs into a compact, portable bundle. The next agent session resumes immediately without burning context tokens.
- **Unified Capsule Storage Server:** A central persistent storage hub (e.g. running on a cloud VM or companion station like `cloud-server` over a private Tailscale network) where all fleet agents automatically upload, query, pull, and synchronize capsules.
- **AHRP Live Relay (In-Session Collaboration):** A real-time WebSocket mesh supporting peer discovery, publish/subscribe messaging, and cross-machine Remote Procedure Calls (RPC).
- **Native MCP Integration:** Works out-of-the-box with Claude Desktop, Antigravity, OpenClaw, and Cursor via the Model Context Protocol.

---

## The Engineering Story

The problem hit me every time I started a fresh agent session: hours of reasoning — rejected paths, working hypotheses, uncommitted diffs — vanished the moment the chat reset or I switched machines. Existing tools saved *code*, but they didn't save the *mind* behind it. I kept losing the cognitive thread.

The breakthrough was separating **cognitive state** from the git tree. A git stash stores a patch; a **Context Capsule** stores the patch *plus* the roadmap, the dead ends, and the exact next step. That single shift turned a resume from "figure it out again" into "continue immediately."

Once capsules solved handoff, I wanted agents to talk *while* they worked. **AHRP Live Relay** gives them a real-time WebSocket mesh: peer discovery, shared beliefs, and direct RPC across machines. Two agents on different computers can literally negotiate a contract and adapt each other's pipelines without human intervention.

With v1.1, we introduced **Unified Capsule Storage**: instead of manual file copies or fragmented local stores, a designated companion machine (such as `cloud-server` over Tailscale) hosts a unified storage server. All agents automatically sync save-states, making context accessible instantly on command and automatically on any node.

---

## Cross-Machine Demo

The video below shows a real capsule packed on **a Windows PC** and unpacked on **a Linux cloud server** with zero context loss.

![Cross-Machine Context Capsule Demo](cross-machine-demo.gif)

**What happens:**
1. On the Windows PC, `agent-comms capsule pack` creates `DEMO-01` with a summary, next step, and epistemic learning.
2. The capsule is automatically synced to the Unified Storage Server on the Linux server over Tailscale.
3. On the Linux server, `agent-comms capsule unpack DEMO-01` restores the exact task briefing — task ID, summary, next action, and learning all intact.

This is the out-of-session handoff problem solved end-to-end across two physical machines.

---

## How It Works

### 1. Unified Capsule Storage & Handoff
Agent Comms captures cognitive state alongside your working tree without polluting Git commit history:
- **State & Decisions:** Records what worked, what was rejected, and the immediate next steps.
- **Code Diffs:** Captures staged, unstaged, and untracked changes into a clean patch.
- **Briefing Generation:** Produces a token-efficient Markdown briefing tailored for the incoming agent.
- **Unified Fleet Storage:** Agents push to and pull from a centralized storage server (e.g. `http://cloud-server:8765`), keeping all machines in sync.

```
Machine A (Active Session)              Unified Storage (Cloud-Server)            Machine B (New Session)
 ┌──────────────────────────┐               ┌───────────────────┐               ┌──────────────────────────┐
 │ Agent exports capsule    │────[Upload]──▶│ Central Capsule   │────[Download]▶│ Agent imports capsule    │
 │ (diffs + state + roadmap)│               │ Persistent Store  │               │ (restores diffs + state) │
 └──────────────────────────┘               └───────────────────┘               └──────────────────────────┘
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
  curl -sSL https://raw.githubusercontent.com/BlahBlah23406/agent-comms/main/install.sh | bash
  ```
- **Windows (PowerShell):**
  ```powershell
  irm https://raw.githubusercontent.com/BlahBlah23406/agent-comms/main/install.ps1 | iex
  ```

Run initial setup:
```bash
agent-comms setup
```

After `git pull`, the next turn automatically reinstalls the instructions, hooks, and Codex settings when they change. Setup only needs to run once.

---

## Quick Usage

### 1. Save Progress (Create a Capsule)
Before ending a session or switching computers:
```bash
agent-comms capsule pack \
  --task "AUTH-01" \
  --summary "Migrated auth module to JWT; integration test pending" \
  --next "Run pytest tests/test_auth.py" \
  --learning "finding:PyJWT requires algorithms=['HS256']" \
  --sync
```

### 2. Unified Capsule Storage Server (Central Hub)
Run a unified persistent capsule storage server on your companion host (e.g. `cloud-server`):
```bash
# Start storage server on host
agent-comms storage server --host 0.0.0.0 --port 8765 --dir ~/.agent-comms/capsules

# Point client machines to the unified storage server (over Tailscale or LAN)
agent-comms config set storage_server_url "http://<server-ip>:8765"
agent-comms config set auto_sync_storage true

# Push / Pull / Sync capsules
agent-comms storage push "AUTH-01"
agent-comms storage pull "AUTH-01" --apply
agent-comms storage sync
agent-comms storage list --remote
```

### 3. Resume on Another Machine
Restore your uncommitted files and task briefing:
```bash
agent-comms capsule unpack "AUTH-01"
```
*(If the capsule isn't stored locally, it is automatically fetched from the unified storage server.)*

### 4. Cloud Capsule Synchronization
Save capsules to external cloud providers (S3, GCS, Azure, GitHub Gists) or the unified storage server:
```bash
# Push capsule to GitHub Gist or AWS S3
agent-comms capsule push "AUTH-01" --cloud github
# or
agent-comms capsule push "AUTH-01" --cloud s3

# Pull and immediately apply patch on another machine
agent-comms capsule pull "AUTH-01" --cloud github --apply
```

### 5. 1-Command Active Cross-Session (Instant Auto-Wake)
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

### 6. Preemptive AI Rate-Limit & Quota Guard
Never lose your work or get stuck mid-task due to AI provider quota exhaustion or rate limits:
- **Autonomous SessionWatchdog:** Runs inside the background standby daemon, actively watching Claude Code and Antigravity logs for rate-limit pauses or 429 exhaustion, and auto-generates an evacuation capsule.
- **Claude Code Lifecycle Hooks:** Integrates deterministic `PreToolUse` and `Stop` hooks in `settings.json` to capture state immediately before a session is blocked.
- **Workspace Briefing:** Writes `PREEMPTIVE_EVACUATION_BRIEFING.md` directly in the project root with the exact resumption prompt for successor models.

```bash
# Check current AI provider quota usage & remaining headroom
agent-comms quota status --provider anthropic

# Run session watchdog in foreground (already active in background standby)
agent-comms quota watch

# Preemptively evacuate session before rate limit lockout
agent-comms quota evacuate --task "AUTH-01" --target gemini
```

### 7. Multi-Machine Node Setup (`--alias`)
Set up any machine in 1 command and automatically link it to your peer network:
```bash
# On primary laptop:
agent-comms setup --alias laptop --peers laptop,desktop-gpu,cloud-server

# On secondary/remote machine (with auto-wake background standby service):
agent-comms setup --alias desktop-gpu --peers laptop,desktop-gpu,cloud-server --standby
```

### 8. Run the Live Collaboration Demo
See two local agents discover each other and collaborate:
```bash
agent-comms demo
```

### 9. Use in Claude Desktop, Claude Code, Antigravity, OpenClaw, or Cursor (MCP)
Agent Comms includes full MCP tooling for Context Capsules, Unified Storage, Cloud, Active Cross-Sessions, and Quota Protection:
- `export_handoff_capsule` (with automatic storage server upload)
- `import_handoff_capsule` (with automatic remote fallback)
- `sync_capsules` (synchronizes local and unified storage)
- `push_handoff_capsule` & `pull_handoff_capsule` & `list_saved_capsules`
- `start_cross_session` & `scan_network_peers`
- `check_quota_status`, `record_usage_and_guard`, & `preemptive_quota_evacuate`
- `save_progress`, `resume_latest`, `run_on_agents`, `check_jobs`, & `agent_status`

Add to your MCP settings file:
```json
{
  "mcpServers": {
    "agent-comms": {
      "command": "agent-comms",
      "args": ["mcp"],
      "env": {
        "AGENT_COMMS_STORAGE_URL": "http://<server-ip>:8765"
      }
    }
  }
}
```

Once added, interact naturally with your agent:
> *"Save my progress into a handoff capsule for task AUTH-01."*  
> *"Resume task AUTH-01 from my latest capsule."*  
> *"Sync our capsules with my storage server."*  
> *"Start an active cross-session with cloud-server for task PERF-99."*  
> *"Check our quota status and evacuate to Gemini if we are close to Claude's rate limit."*

---

## Documentation

- [**Natural Language User Guide** (`USER_GUIDE.md`)](USER_GUIDE.md) — Plain-English prompt examples for Claude Desktop, Claude Code, Antigravity, and Cursor.
- [**Onboarding Guide** (`ONBOARDING.md`)](ONBOARDING.md) — Step-by-step developer onboarding and distributed agent recipes.
- [**Protocol Specification** (`SPECIFICATION.md`)](SPECIFICATION.md) — Formal AHRP wire protocol and JSON schemas.
- [**Tutorial & Recipes** (`TUTORIAL.md`)](TUTORIAL.md) — Hands-on walkthroughs and implementation examples.
