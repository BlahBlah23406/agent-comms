# Hands-On Tutorial: Using `agent-comms`

This tutorial walks you through practical, real-world workflows using the **Agent Communication & Handover Suite (`agent-comms`)**.

---

## 1. Installation

From the `agent-comms` directory, install in editable mode or install dependencies:

```bash
cd %USERPROFILE%gent-comms
pip install -e .
```

You now have the `agent-comms` command available globally in your environment.

Verify the installation:
```bash
agent-comms --help
```

---

## 2. Out-of-Session Handoff: Laptop to Desktop

Imagine you are working with an AI coding agent on your **Laptop**. You need to wrap up, shut your laptop lid, and continue later on your **Desktop** workstation.

### Step 1: Export a Context Capsule on Machine A (Laptop)

From your terminal or agent session in your project folder:

```bash
agent-comms capsule pack \
  --task "AUTH-MIGRATION-102" \
  --title "Migrate Auth to JWT" \
  --summary "Wrote JWT generation logic and tests. Encountered PyJWT algorithm quirk." \
  --goal "Complete auth token refresh endpoints" \
  --next "Run pytest tests/test_auth.py and implement refresh token rotation" \
  --learning "finding:PyJWT requires algorithms=['HS256'] explicitly declared in decode()" \
  --learning "rejected:Tried cookie-based storage, user requested Authorization Bearer header"
```

What this does:
1. Gathers all modified tracked files and computes a clean git unified diff.
2. Identifies all new, untracked files (tests, fixtures, configs) and serializes them.
3. Packages the task goal, checklist, and epistemic learnings into a Context Capsule.
4. Saves `~/.agent-comms/capsules/AUTH-MIGRATION-102_<id>.json` and a companion Markdown briefing `*.md`.

### Step 2: Transfer Capsule to Machine B (Desktop)
Options:
- **Shared Network Drive / Cloud Sync:** Syncs automatically if using Dropbox, Google Drive, or shared NAS.
- **Git Branch:** Commit the capsule file or push to branch.
- **Direct Copy:** `scp`, USB drive, or Tailscale send.
- **Relay Hub:** Upload to your private AHRP Relay server (`curl -X POST ...`).

### Step 3: Resume on Machine B (Desktop)

On your desktop workstation, navigate to your project directory and run:

```bash
agent-comms capsule unpack "AUTH-MIGRATION-102"
```

What this does:
1. Applies the exact unified git diff patch to your workspace cleanly.
2. Recreates all untracked test fixtures and scripts.
3. Outputs the **Resumption Briefing** formatted specifically for your incoming AI agent.

Feed the resulting briefing or prompt to your desktop agent, and it resumes immediately with 100% context and zero wasted tokens!

---

## 3. In-Session Live Collaboration: Real-Time Cross-Machine Mesh

Imagine you are using a lightweight **Developer Laptop**, but you have a high-powered **Cloud GPU / Linux Worker** machine that can execute heavy builds, machine learning tests, or Docker matrices.

### Step 1: Start the Live Relay Hub
On any accessible machine (or your cloud server):

```bash
agent-comms relay server --host 0.0.0.0 --port 8765
```

### Step 2: Connect the Remote Worker Agent (Machine B)
In a Python script or service running on the remote GPU server:

```python
import asyncio
from agent_comms import AgentRelayClient

async def main():
    client = AgentRelayClient(
        agent_id="cloud-gpu-worker",
        machine_id="aws-p3-instance",
        framework="antigravity-worker",
        capabilities=["gpu_acceleration", "docker_build", "test_matrix"],
        relay_url="ws://<relay-ip>:8765/ws",
    )

    # Register an RPC method that the laptop agent can trigger remotely
    async def handle_run_tests(params):
        suite = params.get("suite")
        print(f"Executing test suite '{suite}' on GPU...")
        
        # Stream live progress updates to all subscribers
        await client.publish("job.progress", {"status": "running", "percent": 50})
        await asyncio.sleep(1)
        await client.publish("job.progress", {"status": "complete", "percent": 100})
        
        return {"passed": 142, "failed": 0, "device": "NVIDIA A100"}

    client.register_rpc_handler("run_tests", handle_run_tests)
    await client.connect()
    print("Worker online and waiting for RPC requests...")

    # Keep running
    while True:
        await asyncio.sleep(3600)

asyncio.run(main())
```

### Step 3: Trigger Work from the Developer Laptop (Machine A)

On your laptop, query peers and invoke the remote worker via CLI:

```bash
# Check who is online
agent-comms relay peers --relay ws://<relay-ip>:8765/ws

# Call RPC method on the cloud worker
agent-comms relay rpc \
  --relay ws://<relay-ip>:8765/ws \
  --target cloud-gpu-worker \
  --method run_tests \
  --params "{\"suite\": \"gpu_e2e\"}"
```

The cloud worker executes the workload remotely, publishes real-time milestones, and returns the strongly-typed JSON results directly to your laptop!

---

## 4. Connecting with Antigravity, Claude Code, & Cursor via MCP

The `agent-comms` suite includes a built-in **Model Context Protocol (MCP)** server.

### Add to your MCP Config (e.g. `claude_desktop_config.json` or Antigravity settings):

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

Now, your AI agent has native access to tools:
- `export_handoff_capsule`: Lets the agent voluntarily save its current state and epistemic learnings at milestones.
- `import_handoff_capsule`: Lets the agent resume from another agent's capsule by name or task ID.
- `list_saved_capsules`: Inspects available handoffs in the store.

---

## 5. Running the Test & Verification Suite

To verify all components and run the multi-machine simulation scenarios:

```bash
python tests/run_all.py
```

You should see all unit tests and both cross-machine simulation scenarios pass:
- Unit Tests: `PASSED`
- Out-of-Session Cross-Machine Handoff: `PASSED`
- In-Session Live Cross-Machine Collaboration: `PASSED`
