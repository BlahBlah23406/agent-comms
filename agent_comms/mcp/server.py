"""
Model Context Protocol (MCP) Server
===================================
Exposes Context Capsule handoff, Cloud Storage synchronization, and Live Cross-Session
activation as standardized MCP tools for AI assistants (Antigravity, Claude, Cursor, Windsurf).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.capsule.unpacker import CapsuleUnpacker
from agent_comms.models.capsule import EpistemicLearning, LearningCategory, TaskStep, StepStatus
from agent_comms.quota.guard import QuotaGuard
from agent_comms.session.discovery import UDPDiscoveryBroadcaster
from agent_comms.session.manager import CrossSessionManager


class AgentCommsMCPServer:
    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace_path = workspace_path or Path.cwd()
        self.store = CapsuleStore()
        self.packager = CapsulePackager(workspace_path=self.workspace_path, store=self.store)
        self.unpacker = CapsuleUnpacker(workspace_path=self.workspace_path)
        self.session_mgr = CrossSessionManager(workspace_path=self.workspace_path)
        self.quota_guard = QuotaGuard(workspace_path=self.workspace_path, store=self.store)

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "export_handoff_capsule",
                "description": "Packages current task progress, epistemic learnings, git changes, and next steps into a transferable Context Capsule. Optionally pushes to cloud.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Unique task or issue ID"},
                        "title": {"type": "string", "description": "Descriptive title"},
                        "goal": {"type": "string", "description": "Overall task goal"},
                        "executive_summary": {"type": "string", "description": "Summary of work done so far"},
                        "next_action": {"type": "string", "description": "Specific next instruction for successor agent"},
                        "push_to_cloud": {"type": "boolean", "default": False, "description": "Whether to automatically upload capsule to cloud storage"},
                        "cloud_provider": {"type": "string", "description": "Target cloud provider (s3, gcs, azure, github, relay)"},
                        "epistemic_learnings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {"type": "string", "enum": ["finding", "rejected", "gotcha", "environment", "constraint"]},
                                    "summary": {"type": "string"},
                                    "details": {"type": "string"},
                                    "evidence": {"type": "string"},
                                },
                                "required": ["category", "summary"],
                            },
                            "description": "Key discoveries, rejected hypotheses, or constraints discovered during the session",
                        },
                    },
                    "required": ["task_id", "title", "goal", "executive_summary", "next_action"],
                },
            },
            {
                "name": "import_handoff_capsule",
                "description": "Imports and applies a Context Capsule from local store or cloud, restoring workspace changes and briefing context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_or_task_id": {"type": "string", "description": "ID of the capsule, task, or cloud URI to import"},
                        "apply_workspace": {"type": "boolean", "default": True, "description": "Whether to apply git diffs and untracked files"},
                        "cloud_provider": {"type": "string", "description": "Optional explicit cloud provider to pull from if not found locally"},
                    },
                    "required": ["capsule_or_task_id"],
                },
            },
            {
                "name": "push_handoff_capsule",
                "description": "Pushes a Context Capsule to cloud storage (S3, GCS, Azure, GitHub, or Relay).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_id": {"type": "string", "description": "ID of the capsule or task to push"},
                        "cloud_provider": {"type": "string", "description": "Target cloud provider (s3, gcs, azure, github, relay)"},
                    },
                    "required": ["capsule_id"],
                },
            },
            {
                "name": "pull_handoff_capsule",
                "description": "Pulls a Context Capsule from cloud storage and optionally applies it directly to the workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_id": {"type": "string", "description": "ID of the capsule or cloud URI"},
                        "cloud_provider": {"type": "string", "description": "Source cloud provider (s3, gcs, azure, github, relay)"},
                        "apply_workspace": {"type": "boolean", "default": True, "description": "Whether to apply git diffs and restored files"},
                    },
                    "required": ["capsule_id"],
                },
            },
            {
                "name": "list_saved_capsules",
                "description": "Lists all available Context Capsules in the local store.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_cloud_capsules",
                "description": "Lists Context Capsules stored on the cloud provider.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cloud_provider": {"type": "string", "description": "Cloud provider (s3, gcs, azure, github, relay)"},
                    },
                },
            },
            {
                "name": "start_cross_session",
                "description": "Starts an active collaborative cross-machine session, waking up standby machines on LAN/Relay and linking mental models.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target_machine": {"type": "string", "description": "Alias of the remote machine to wake (or omit to wake all available)"},
                        "task_id": {"type": "string", "description": "Optional task identifier to auto-package and transmit to the remote machine"},
                        "room_id": {"type": "string", "description": "Optional custom room/session identifier"},
                    },
                },
            },
            {
                "name": "scan_network_peers",
                "description": "Scans the local network for standby agent machines available for instant cross-session collaboration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "check_quota_status",
                "description": "Inspects quota utilization and rate limit health for an AI provider (anthropic, openai, gemini, cursor, custom).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "description": "AI provider name e.g. anthropic, openai, gemini, cursor"},
                    },
                    "required": ["provider"],
                },
            },
            {
                "name": "record_usage_and_guard",
                "description": "Records API tokens/requests used, parses response headers, and warns if rate limit is imminent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "description": "AI provider name"},
                        "tokens_used": {"type": "integer", "default": 0},
                        "requests_used": {"type": "integer", "default": 1},
                        "headers": {"type": "object", "description": "Optional HTTP response headers from AI provider"},
                    },
                    "required": ["provider"],
                },
            },
            {
                "name": "preemptive_quota_evacuate",
                "description": "Preemptively freezes session before hitting an AI provider rate limit, saves git diffs & task progress to a Context Capsule, and optionally pushes to cloud for another agent/provider to resume.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task identifier to freeze and handoff"},
                        "provider": {"type": "string", "description": "Current AI provider being exhausted"},
                        "summary": {"type": "string", "description": "Summary of completed work before rate-limit shutdown"},
                        "next_action": {"type": "string", "description": "Immediate instructions for the successor agent"},
                        "target_provider": {"type": "string", "description": "Recommended alternative provider or account (e.g. gemini, openai, secondary-account)"},
                        "push_to_cloud": {"type": "boolean", "default": True, "description": "Upload capsule to cloud for another machine/agent to pick up"},
                    },
                    "required": ["task_id", "provider"],
                },
            },
        ]

    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> str:
        if name == "export_handoff_capsule":
            learnings = []
            for item in arguments.get("epistemic_learnings", []):
                learnings.append(
                    EpistemicLearning(
                        category=LearningCategory(item["category"]),
                        summary=item["summary"],
                        details=item.get("details"),
                        evidence=item.get("evidence"),
                    )
                )

            capsule = self.packager.package(
                task_id=arguments["task_id"],
                title=arguments["title"],
                executive_summary=arguments["executive_summary"],
                goal=arguments["goal"],
                next_action=arguments["next_action"],
                epistemic_learnings=learnings,
            )
            saved_path = self.store.save(capsule)
            cloud_loc = None
            if arguments.get("push_to_cloud"):
                try:
                    cloud_loc = self.store.push_to_cloud(
                        capsule, provider_name=arguments.get("cloud_provider")
                    )
                except Exception as ex:
                    cloud_loc = f"Upload error: {ex}"

            res = {
                "status": "success",
                "capsule_id": capsule.capsule_id,
                "saved_path": str(saved_path),
                "briefing": capsule.to_briefing_markdown(),
            }
            if cloud_loc:
                res["cloud_location"] = cloud_loc
            return json.dumps(res, indent=2)

        elif name == "import_handoff_capsule":
            target_id = arguments["capsule_or_task_id"]
            capsule = self.store.load_by_id(target_id)
            if not capsule:
                p = Path(target_id)
                if p.exists() and p.is_file():
                    capsule = self.store.load_from_file(p)

            # Fallback to cloud if not found locally
            if not capsule:
                try:
                    capsule = self.store.pull_from_cloud(
                        target_id, provider_name=arguments.get("cloud_provider")
                    )
                except Exception:
                    pass

            if not capsule:
                return json.dumps({"error": f"Capsule '{target_id}' not found locally or on cloud."}, indent=2)

            apply_ws = arguments.get("apply_workspace", True)
            res = self.unpacker.apply(capsule, apply_workspace=apply_ws)
            return json.dumps({
                "status": "success",
                "capsule_id": capsule.capsule_id,
                "restoration": res,
                "resumption_prompt": capsule.resumption_prompt,
            }, indent=2)

        elif name == "push_handoff_capsule":
            cid = arguments["capsule_id"]
            try:
                location = self.store.push_to_cloud(
                    cid, provider_name=arguments.get("cloud_provider")
                )
                return json.dumps({"status": "success", "capsule_id": cid, "location": location}, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Push failed: {e}"}, indent=2)

        elif name == "pull_handoff_capsule":
            cid = arguments["capsule_id"]
            try:
                capsule = self.store.pull_from_cloud(
                    cid, provider_name=arguments.get("cloud_provider"), save_local=True
                )
                res = {"status": "success", "capsule_id": capsule.capsule_id, "task_id": capsule.task_id}
                if arguments.get("apply_workspace", True):
                    unpacked = self.unpacker.apply(capsule, apply_workspace=True)
                    res["restoration"] = unpacked
                return json.dumps(res, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Pull failed: {e}"}, indent=2)

        elif name == "list_saved_capsules":
            caps = self.store.list_capsules()
            return json.dumps([
                {
                    "capsule_id": c.capsule_id,
                    "task_id": c.task_id,
                    "title": c.title,
                    "created_at": c.created_at,
                    "origin": f"{c.generator.agent_name}@{c.generator.machine_id}",
                    "summary": c.executive_summary,
                }
                for c in caps
            ], indent=2)

        elif name == "list_cloud_capsules":
            try:
                caps = self.store.list_cloud_capsules(provider_name=arguments.get("cloud_provider"))
                return json.dumps([c.model_dump() for c in caps], indent=2)
            except Exception as e:
                return json.dumps({"error": f"Error querying cloud: {e}"}, indent=2)

        elif name == "start_cross_session":
            target = arguments.get("target_machine")
            task_id = arguments.get("task_id")
            room = arguments.get("room_id")

            capsule = None
            if task_id:
                capsule = self.store.load_by_id(task_id)

            try:
                session = await self.session_mgr.start_session(
                    session_id=room,
                    target_machine=target,
                    capsule_or_id=capsule,
                    timeout=5.0,
                )
                return json.dumps({
                    "status": "success",
                    "session_id": session.session_id,
                    "relay_url": session.relay_url,
                    "connected_peers": session.connected_peers,
                    "message": f"Active cross-session live! Connected peers: {session.connected_peers or 'None (waiting for join)'}",
                }, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Failed to start cross-session: {e}"}, indent=2)

        elif name == "scan_network_peers":
            broadcaster = UDPDiscoveryBroadcaster()
            peers = await broadcaster.discover_peers(timeout=1.5)
            return json.dumps([p.to_dict() for p in peers], indent=2)

        elif name == "check_quota_status":
            provider = arguments["provider"]
            status = self.quota_guard.check_quota(provider)
            return json.dumps(status.model_dump(), indent=2)

        elif name == "record_usage_and_guard":
            provider = arguments["provider"]
            tokens = arguments.get("tokens_used", 0)
            reqs = arguments.get("requests_used", 1)
            headers = arguments.get("headers")
            status = self.quota_guard.record_interaction(
                provider=provider,
                tokens_used=tokens,
                requests_used=reqs,
                headers=headers,
            )
            return json.dumps(status.model_dump(), indent=2)

        elif name == "preemptive_quota_evacuate":
            task_id = arguments["task_id"]
            provider = arguments["provider"]
            summary = arguments.get("summary", f"Preemptive evacuation before {provider} rate limit")
            next_action = arguments.get("next_action")
            target_provider = arguments.get("target_provider")
            push_cloud = arguments.get("push_to_cloud", True)

            result = self.quota_guard.force_evacuate(
                task_id=task_id,
                provider=provider,
                summary=summary,
                next_action=next_action,
                target_provider=target_provider,
                auto_push_cloud=push_cloud,
            )
            return json.dumps(result.model_dump(), indent=2)

        return json.dumps({"error": f"Unknown tool: {name}"})

    async def run_stdio(self):
        """Standard IO JSON-RPC 2.0 MCP loop."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except Exception:
                continue

            msg_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "agent-comms-mcp", "version": "1.1.0"},
                    },
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": self.get_tools()},
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                args = params.get("arguments", {})
                tool_result = await self.handle_tool_call(tool_name, args)
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": tool_result}]
                    },
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
