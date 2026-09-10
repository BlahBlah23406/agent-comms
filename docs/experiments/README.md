# Multi-Machine Live Experiments Archive

This directory contains the complete technical reports, telemetry data, and reproducible execution scripts from the live multi-machine validation experiments performed between **Providence** (Windows 11) and **code-47** (Oracle Cloud Ubuntu 24.04).

---

## Experiments Index

### 1. [Experiment 1: Orchestrator / Worker Collaboration](01_ORCHESTRATOR_WORKER_EXPERIMENT.md)
* **Paradigm:** Hierarchical coordination (Master / Worker).
* **Workload:** Real-time collaborative planning on `channel.planning`, followed by live RPC invocation across the WAN harvesting real Linux kernel metrics (`/proc/loadavg`, `/proc/meminfo`, `/proc/net/tcp`).
* **Source Code:** [`code/orchestrator_worker/`](code/orchestrator_worker/)
* **Outcome:** Sub-second autonomous consensus; verified real-time stream; persisted AHRP Context Capsule.

### 2. [Experiment 2: Peer-to-Peer Dual-Brain Distributed Pipeline](02_PEER_TO_PEER_DUAL_BRAIN_EXPERIMENT.md)
* **Paradigm:** Peer parity ("Two Computers, Two Agents, One Mind").
* **Workload:** Multi-server closed-loop pipeline ring (Windows `:9201` ingest & proof ledger, Linux `:9202` numerical transform & Merkle tree engine). **Neither computer could complete the task alone.**
* **Key Innovations:**
  * Symmetrical contract negotiation (`P2P_Batch_Contract`) locked via consensus in `<1.0s`.
  * Replicated `CognitiveBlackboard` with live cognitive deltas.
  * **Dynamic Runtime Adaptation**: Linux peer discovered vector presorting improved CPU branch prediction; asserted delta; Windows peer mutated running generator on the fly without service restarts.
  * Cryptographic Merkle verification across all batches.
  * Twin Context Capsules exported on both machines.
* **Source Code:** [`code/dual_brain_p2p/`](code/dual_brain_p2p/)
