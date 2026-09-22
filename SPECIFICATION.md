# Agent Handover & Relay Protocol (AHRP) Specification (v1.0.0)

## 1. Overview & Objectives

The **Agent Handover & Relay Protocol (AHRP)** provides an open, vendor-neutral standard for transferring cognitive state, task progression, and physical workspace deltas across autonomous AI agents and physical host machines.

AHRP operates across two complementary sub-protocols:
1. **AHRP-Capsule (Out-of-Session):** Deterministic schema for packaging, persisting, and restoring an agent's mental model and workspace state.
2. **AHRP-Relay (In-Session):** Real-time WebSocket/HTTP event mesh enabling peer discovery, topic publish/subscribe, and remote procedure calls (RPC).

---

## 2. AHRP-Capsule: Out-of-Session Schema

A Context Capsule is a self-contained JSON document (accompanied by a human/agent-readable Markdown companion) that encapsulates everything required for another agent to immediately assume responsibility for a task.

### 2.1 Schema Definition

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ContextCapsule",
  "type": "object",
  "required": [
    "schema_version",
    "capsule_id",
    "task_id",
    "title",
    "created_at",
    "generator",
    "executive_summary",
    "task_graph"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0.0" },
    "capsule_id": { "type": "string" },
    "task_id": { "type": "string" },
    "title": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "generator": {
      "type": "object",
      "required": ["agent_name", "machine_id", "os_name"],
      "properties": {
        "agent_name": { "type": "string" },
        "agent_version": { "type": "string" },
        "machine_id": { "type": "string" },
        "os_name": { "type": "string" },
        "session_id": { "type": "string" }
      }
    },
    "target_agent": { "type": ["string", "null"] },
    "executive_summary": { "type": "string" },
    "task_graph": {
      "type": "object",
      "required": ["goal"],
      "properties": {
        "goal": { "type": "string" },
        "steps": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["description", "status"],
            "properties": {
              "id": { "type": "string" },
              "description": { "type": "string" },
              "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "blocked", "skipped"]
              },
              "notes": { "type": "string" }
            }
          }
        },
        "next_action": { "type": "string" }
      }
    },
    "epistemic_learnings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["category", "summary"],
        "properties": {
          "category": {
            "type": "string",
            "enum": ["finding", "rejected", "gotcha", "environment", "constraint"]
          },
          "summary": { "type": "string" },
          "details": { "type": "string" },
          "evidence": { "type": "string" }
        }
      }
    },
    "workspace": {
      "type": "object",
      "properties": {
        "is_git_repo": { "type": "boolean" },
        "repo_root": { "type": "string" },
        "branch_name": { "type": "string" },
        "base_commit": { "type": "string" },
        "git_diff": { "type": "string" },
        "untracked_files": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        },
        "modified_files": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    },
    "resumption_prompt": { "type": "string" },
    "extra_metadata": { "type": "object" }
  }
}
```

### 2.2 Epistemic Learning Taxonomy
To prevent successor agents from repeating redundant exploration or failing known invariants:
- **`finding`**: Verified fact, discovered architecture, or established baseline.
- **`rejected`**: Approach or hypothesis attempted and discarded (crucial for breaking loop cycles).
- **`gotcha`**: Counter-intuitive behavior, library quirk, or edge case.
- **`environment`**: Required runtime flags, compiler versions, or environment variables.
- **`constraint`**: Invariant requested by user or demanded by domain architecture.

---

## 3. AHRP-Relay: In-Session Wire Protocol

The live relay enables real-time peer-to-peer and broadcast messaging over a central hub (or mesh).

### 3.1 Transport & Frame Format
All messages over WebSocket are UTF-8 encoded JSON matching the `RelayFrame` specification:

```json
{
  "frame_id": "frm-9b2e4f01c8a7",
  "type": "rpc_request",
  "sender_id": "agent_laptop",
  "machine_id": "workstation-pro",
  "target_id": "agent_cloud_worker",
  "topic": null,
  "request_id": "rpc-82bc19fa",
  "payload": {
    "method": "run_test_matrix",
    "params": { "suite": "e2e" }
  },
  "error": null,
  "timestamp": "2026-09-10T12:00:00.000000Z"
}
```

### 3.2 Frame Types

| Frame Type | Initiator | Description |
| :--- | :--- | :--- |
| `register` | Client | Initial handshake declaring agent ID, host, and capabilities. |
| `register_ack` | Server | Server acknowledgment confirming registration. |
| `peer_list_req` | Client | Queries server for active online agents. |
| `peer_list_resp` | Server | Returns list of `AgentDescriptor` records. |
| `subscribe` | Client | Subscribes client to a broadcast topic. |
| `unsubscribe` | Client | Unsubscribes client from a broadcast topic. |
| `publish` | Client | Broadcasts payload to all agents subscribed to `topic`. |
| `message` | Client | Unicast point-to-point message directed to `target_id`. |
| `rpc_request` | Client | Invokes method on target agent, awaiting correlated response. |
| `rpc_response` | Client | Delivers return value of method correlated by `request_id`. |
| `activate_session` | Client | Commands standby machine to awaken, receive context, and join session. |
| `session_activated` | Client | Acknowledgment confirming target machine is awake and linked. |
| `capsule_transfer` | Client | High-bandwidth direct Context Capsule transfer over WebSocket mesh. |
| `heartbeat` | Client | Keepalive ping frame. |
| `pong` | Server | Keepalive acknowledgment. |
| `error` | Any | Error notification frame. |

---

## 4. Security & Network Topologies

1. **Local Network / Direct Connect:**
   Suitable for LAN or localhost multi-agent pair programming.
2. **Mesh Networks (Tailscale / WireGuard):**
   Recommended for distributed multi-computer agent workflows. Tailscale assigns stable IP addresses (e.g. `100.x.y.z`) across all developer laptops, desktops, and cloud VMs without port-forwarding or public ingress.
3. **Transport Layer Security (TLS):**
   Production relay instances terminate TLS (`wss://` and `https://`) via reverse proxy (Caddy, Nginx, or Cloudflare).
4. **Authentication:**
   Bearer token authentication header evaluated during WebSocket handshake.

---

## 5. AHRP-Discovery: LAN Zero-Config Beacon (UDP:8764)

To eliminate manual IP configuration and firewall friction between computers on the same network, AHRP specifies a lightweight UDP discovery and wake-up protocol:

### 5.1 Discovery Ping & Pong
- **Broadcast:** Initiator sends `{"type": "DISCOVERY_PING", "machine_id": "laptop"}` to `255.255.255.255:8764`.
- **Response:** Standby listeners reply with `{"type": "DISCOVERY_PONG", "machine_id": "desktop", "ip": "192.168.1.50", "status": "standby"}`.

### 5.2 Auto-Wake Packet (`WAKE_ACTIVATE`)
- **Broadcast:** Initiator sends `{"type": "WAKE_ACTIVATE", "session_id": "...", "relay_url": "ws://...", "capsule": {...}}`.
- **Action:** Standby daemon receives packet, unpacks Context Capsule into local workspace, connects `DualBrainNode` to relay, and replies with `WAKE_ACK`.

---

## 6. AHRP-Cloud: Pluggable Cloud Repository Standard

Capsules can be transferred through decentralized or cloud object storage backends:
- **AWS S3 / Compatible (MinIO, R2, Wasabi):** `s3://<bucket>/capsules/<task_id>_<capsule_id>.json`
- **Google Cloud Storage (GCS):** `gs://<bucket>/capsules/<task_id>_<capsule_id>.json`
- **Azure Blob Storage:** `azure://<container>/capsules/<task_id>_<capsule_id>.json`
- **GitHub Gists:** `github://gist/<gist_id>` (Secret Gist containing JSON and companion Markdown)
- **Relay Hub REST:** `relay://<host>:<port>/capsules/<capsule_id>`
