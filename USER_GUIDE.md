# Natural Language User Guide: Using Agent Comms with Claude & Antigravity

> **The 10-Second Summary:**  
> You don't need to run terminal commands, write bash scripts, or memorize CLI flags. Because `agent-comms` is installed as an **MCP (Model Context Protocol) tool**, you interact with it simply by **talking naturally to Claude, Antigravity, or Cursor**.

---

## 💬 Everyday Prompt Cheat Sheet

Here are exact phrases you can copy and paste into **Claude Desktop**, **Antigravity**, or **Cursor**:

| What You Want to Do | Exact Prompt to Use | What the AI Does |
| :--- | :--- | :--- |
| **Save your work before switching machines** | *"Hey Claude, please save my current progress into a handoff capsule for task AUTH-01. Note that we switched tokens to HS256 and the next step is running pytest."* | Packages your uncommitted Git diffs, saves any untracked files, structures your mental thoughts, and saves a capsule. |
| **Resume work on another computer** | *"Antigravity, please resume task AUTH-01 from my latest capsule."* | Restores your uncommitted code, unpacks any new files, and reads the summary without burning 100,000 chat tokens. |
| **Check what work is saved** | *"What handoff capsules do I have saved?"* | Queries the local store and gives you a clean list of past tasks, authors, and dates. |
| **Handoff a bug with tricky gotchas** | *"Package a capsule for BUG-102. Make sure to record that Postgres on Ubuntu uses port 5433 instead of 5432, and SQLite was rejected due to locking issues."* | Records the gotcha and rejected hypothesis into the capsule so the next agent doesn't repeat your mistakes. |
| **Collaborate live with another machine** | *"Antigravity, connect to our live agent mesh on <server-ip>:8765 and propose a data contract to the remote worker."* | Connects to the real-time WebSocket mesh and shares mental models live. |

---

## 🔄 The 3-Step Cross-Device Workflow

### Step 1: Wrap Up on Machine A (e.g. Your Mac)
When you are about to close your laptop, open Claude or Antigravity and say:

```text
"Save a handoff capsule for our current task (DATA-STREAM). We finished the ingestion module, but the batch transform still has a minor syntax bug on line 42."
```

👉 **Result:** The AI automatically invokes `export_handoff_capsule`. Your half-written code and your mental thoughts are securely packaged. **You don't even have to git commit or push broken code.**

---

### Step 2: Sync the Capsule
Capsules are lightweight JSON files stored in `~/.agent-comms/capsules/`.
* If you use iCloud, OneDrive, Dropbox, or Git sync for that folder, it syncs automatically.
* Or you can simply ask the agent to transfer it over Tailscale / SSH.

---

### Step 3: Pick Up on Machine B (e.g. Your Windows PC or Cloud Linux Server)
Sit down at your other computer, open your AI assistant, and say:

```text
"Resume DATA-STREAM from the capsule."
```

👉 **Result:** The AI automatically invokes `import_handoff_capsule`. 
* Your exact uncommitted files reappear on disk.
* The AI immediately says: *"Resumed DATA-STREAM. Ingestion module is complete; ready to fix the syntax bug on line 42 of the transform module."*
* **No token bloat, no copy-pasting chat history, no context loss.**

---

## ⚡ Live Simultaneous Collaboration ("Two Agents, One Mind")

If you want an agent on your **Mac** and an agent on your **Linux Cloud Server** to work on a distributed project **simultaneously in real time**:

```
┌───────────────────────────┐                       ┌───────────────────────────┐
│     Agent on Laptop       │                       │     Agent on Cloud Node   │
│     (e.g. Mac / Windows)  │                       │     (e.g. Ubuntu Linux)   │
│                           │                       │                           │
│  "Let's split the work:   │                       │  "Contract accepted!      │
│   I'll generate batches,  │◄─────[Live Mesh]─────►│   I'll run GPU transforms │
│   you run the transforms" │                       │   and verify Merkle roots"│
└───────────────────────────┘                       └───────────────────────────┘
```

### How to trigger it naturally:
1. **On your server**, keep the relay broker active:
   ```bash
   agent-comms relay server --port 8765
   ```
2. **Tell your local agent**:
   > *"Launch our dual-brain peer session with remote-worker at ws://<server-ip>:8765/ws. Have the remote worker run the telemetry probe while we verify the results here."*

3. **What happens:**
   Both agents join the shared **Cognitive Blackboard**. When the Linux agent discovers a performance trick (like CPU memory alignment), it broadcasts a **Cognitive Delta**, and your local agent **dynamically adapts its code on the fly without stopping the session.**

---

## ❓ Frequently Asked Questions

### 1. Do I need to be a programmer to use this?
**No.** As long as you have Claude Desktop, Antigravity, or Cursor running, you can speak to it in plain English. The AI knows how to call the underlying tools.

### 2. Why not just copy and paste my chat history?
Copy-pasting chat history wastes 50,000+ tokens, costs money, slows down the AI, and causes "context drift" (the AI forgets details from earlier). A Context Capsule compresses only the **diffs and essential decisions**, keeping the AI sharp and fast.

### 3. Why not just use Git commits (`git commit -m "wip"`)?
Git commits are meant for clean, working checkpoints. If your code doesn't compile yet, or you have half-tested scratch files, committing to Git pollutes your project history. A Context Capsule lets you save **dirty, uncommitted, in-progress workspace state** without touching your Git commit tree.

### 4. Which AI apps work with this?
* **Claude Desktop** (via MCP)
* **Google Antigravity (`agy` & IDE)** (via MCP & Skills)
* **Cursor & Windsurf** (via MCP configuration)
* **Terminal / Python** (via `agent-comms` CLI and Python SDK)
