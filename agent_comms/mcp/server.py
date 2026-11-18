"""
Model Context Protocol (MCP) Server
===================================
Exposes Context Capsule handoff, Unified Storage synchronization, and Live Cross-Session
activation as standardized MCP tools for AI assistants (Antigravity, Claude, OpenClaw, Cursor, Windsurf).
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
                "description": "Packages current task progress, epistemic learnings, git changes, and next steps into a transferable Context Capsule. Optionally persists to unified storage server or cloud.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Unique task or issue ID"},
                        "title": {"type": "string", "description": "Descriptive title"},
                        "goal": {"type": "string", "description": "Overall task goal"},
                        "executive_summary": {"type": "string", "description": "Summary of work done so far"},
                        "next_action": {"type": "string", "description": "Specific next instruction for successor agent"},
                        "push_to_storage": {"type": "boolean", "default": True, "description": "Whether to automatically upload capsule to unified storage server on code-47"},
                        "push_to_cloud": {"type": "boolean", "default": False, "description": "Whether to upload capsule to external cloud storage (s3, gcs, azure, github)"},
                        "cloud_provider": {"type": "string", "description": "Target cloud provider"},
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
                "description": "Imports and applies a Context Capsule from local store or unified storage server on code-47, restoring workspace changes and briefing context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_or_task_id": {"type": "string", "description": "ID of the capsule, task, or URI to import"},
                        "apply_workspace": {"type": "boolean", "default": True, "description": "Whether to apply git diffs and untracked files"},
                        "cloud_provider": {"type": "string", "description": "Optional explicit provider to pull from"},
                    },
                    "required": ["capsule_or_task_id"],
                },
            },
            {
                "name": "push_handoff_capsule",
                "description": "Pushes a Context Capsule to unified storage server or cloud storage.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_id": {"type": "string", "description": "ID of the capsule or task to push"},
                        "cloud_provider": {"type": "string", "description": "Target provider (storage, relay, s3, gcs, azure, github)"},
                    },
                    "required": ["capsule_id"],
                },
            },
            {
                "name": "pull_handoff_capsule",
                "description": "Pulls a Context Capsule from unified storage server or cloud and optionally applies it directly to the workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_id": {"type": "string", "description": "ID of the capsule or URI"},
                        "cloud_provider": {"type": "string", "description": "Source provider (storage, relay, s3, gcs, azure, github)"},
                        "apply_workspace": {"type": "boolean", "default": True, "description": "Whether to apply git diffs and restored files"},
                    },
                    "required": ["capsule_id"],
                },
            },
            {
                "name": "list_saved_capsules",
                "description": "Lists all available Context Capsules in the local store and fleet-wide unified storage server on code-47.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_remote": {"type": "boolean", "default": True, "description": "Whether to include remote capsules from unified storage server"},
                    },
                },
            },
            {
                "name": "sync_capsules",
                "description": "Synchronizes Context Capsules between local machine and the unified storage server on code-47.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "enum": ["both", "push", "pull"], "default": "both", "description": "Sync direction"},
                    },
                },
            },
            {
                "name": "list_cloud_capsules",
                "description": "Lists Context Capsules stored on the cloud/storage provider.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cloud_provider": {"type": "string", "description": "Cloud provider (storage, relay, s3, gcs, azure, github)"},
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
                        "room_id": {"type": "string", "description": "Optional room name or topic"},
                    },
                },
            },
            {
                "name": "scan_network_peers",
                "description": "Scans local network for available standby worker nodes awaiting activation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "check_quota_status",
                "description": "Queries the remaining request and token quota for an AI provider (e.g. 'claude', 'gemini').",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "description": "AI provider name (claude, gemini, openai)"},
                    },
                    "required": ["provider"],
                },
            },
            {
                "name": "record_usage_and_guard",
                "description": "Records token and request consumption, inspects rate limit headers, and checks if evacuation is warranted.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "description": "AI provider name"},
                        "tokens_used": {"type": "integer", "default": 0, "description": "Estimated tokens consumed in turn"},
                        "requests_used": {"type": "integer", "default": 1, "description": "Requests consumed"},
                        "headers": {"type": "object", "description": "HTTP response headers for ratelimit parsing"},
                    },
                    "required": ["provider"],
                },
            },
            {
                "name": "preemptive_quota_evacuate",
                "description": "Emergency command: packages current state into a capsule and halts execution when quota is nearly exhausted.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Active task identifier"},
                        "provider": {"type": "string", "description": "Exhausted provider name"},
                        "summary": {"type": "string", "description": "Reason for evacuation and work done so far"},
                        "next_action": {"type": "string", "description": "Next step for successor agent"},
                        "target_provider": {"type": "string", "description": "Recommended successor provider (e.g. gemini)"},
                        "push_to_cloud": {"type": "boolean", "default": True, "description": "Whether to auto-upload handoff capsule"},
                    },
                    "required": ["task_id", "provider"],
                },
            },
            {
                "name": "save_progress",
                "description": "Saves where this chat is at so any other app or agent can continue it. Chat apps: call this after every second reply.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Short project name (use the code folder name if there is one)"},
                        "goal": {"type": "string", "description": "What the user wants overall"},
                        "summary": {"type": "string", "description": "What is done so far and key decisions"},
                        "next_step": {"type": "string", "description": "The very next thing to do"},
                        "app": {"type": "string", "description": "Which app you are, e.g. claude-desktop, gemini-app"},
                    },
                    "required": ["project", "goal", "summary", "next_step"],
                },
            },
            {
                "name": "resume_latest",
                "description": "Gets the newest saved work for a project (saved by any app or agent on any machine) so you can continue it.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project or folder name; defaults to the current folder"},
                        "task_id": {"type": "string", "description": "Optional exact task ID"},
                        "apply_workspace": {"type": "boolean", "default": False, "description": "Also restore the saved code changes (use when moving to another machine)"},
                    },
                },
            },
            {
                "name": "run_on_agents",
                "description": "Hands tasks to other agent CLIs (claude, codex, gemini, agy, SSH hosts) in the background, picking the least used one for each. Returns job IDs right away; read results with check_jobs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tasks": {"type": "array", "items": {"type": "string"}, "description": "One complete, self-contained instruction per helper. Give each helper different files."},
                        "agent": {"type": "string", "description": "Optional: force one agent, e.g. codex or claude@my-server"},
                        "folder": {"type": "string", "description": "Project folder the helpers work in (needed from chat apps)"},
                    },
                    "required": ["tasks"],
                },
            },
            {
                "name": "check_jobs",
                "description": "Shows the status and output of helper jobs. Set wait_seconds to wait for them to finish.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_ids": {"type": "array", "items": {"type": "string"}},
                        "wait_seconds": {"type": "integer", "default": 0},
                    },
                    "required": ["job_ids"],
                },
            },
            {
                "name": "agent_status",
                "description": "Lists the agent CLIs ready to take work, how much each was used in the last 5 hours, and which are resting after hitting a limit.",
                "inputSchema": {"type": "object", "properties": {}},
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
            storage_loc = None
            if arguments.get("push_to_storage", True) and self.store.storage_url:
                try:
                    storage_loc = self.store.push_to_storage(capsule)
                except Exception as ex:
                    storage_loc = f"Storage sync warning: {ex}"

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
            if storage_loc:
                res["storage_location"] = storage_loc
            if cloud_loc:
                res["cloud_location"] = cloud_loc
            return json.dumps(res, indent=2)

        elif name == "import_handoff_capsule":
            target_id = arguments["capsule_or_task_id"]
            capsule = self.store.load_by_id(target_id, fetch_remote=True)
            if not capsule:
                p = Path(target_id)
                if p.exists() and p.is_file():
                    capsule = self.store.load_from_file(p)

            # Fallback to explicit cloud provider if specified
            if not capsule and arguments.get("cloud_provider"):
                try:
                    capsule = self.store.pull_from_cloud(
                        target_id, provider_name=arguments.get("cloud_provider")
                    )
                except Exception:
                    pass

            if not capsule:
                return json.dumps({"error": f"Capsule '{target_id}' not found locally or in unified storage."}, indent=2)

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
            provider = arguments.get("cloud_provider")
            try:
                if not provider or provider in ("storage", "server"):
                    location = self.store.push_to_storage(cid)
                else:
                    location = self.store.push_to_cloud(cid, provider_name=provider)
                return json.dumps({"status": "success", "capsule_id": cid, "location": location}, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Push failed: {e}"}, indent=2)

        elif name == "pull_handoff_capsule":
            cid = arguments["capsule_id"]
            provider = arguments.get("cloud_provider")
            try:
                if not provider or provider in ("storage", "server"):
                    capsule = self.store.pull_from_storage(cid, save_local=True)
                else:
                    capsule = self.store.pull_from_cloud(cid, provider_name=provider, save_local=True)

                res = {"status": "success", "capsule_id": capsule.capsule_id, "task_id": capsule.task_id}
                if arguments.get("apply_workspace", True):
                    unpacked = self.unpacker.apply(capsule, apply_workspace=True)
                    res["restoration"] = unpacked
                return json.dumps(res, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Pull failed: {e}"}, indent=2)

        elif name == "list_saved_capsules":
            include_remote = arguments.get("include_remote", True)
            caps = self.store.list_capsules(include_remote=include_remote)
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

        elif name == "sync_capsules":
            direction = arguments.get("direction", "both")
            try:
                result = self.store.sync(direction=direction)
                return json.dumps({"status": "success", "result": result}, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Sync failed: {e}"}, indent=2)

        elif name == "list_cloud_capsules":
            try:
                provider = arguments.get("cloud_provider")
                if not provider or provider in ("storage", "server"):
                    caps = self.store.list_storage_capsules()
                else:
                    caps = self.store.list_cloud_capsules(provider_name=provider)
                return json.dumps([c.model_dump() for c in caps], indent=2)
            except Exception as e:
                return json.dumps({"error": f"Error querying remote storage: {e}"}, indent=2)

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

        elif name == "save_progress":
            from agent_comms.fleet.autosave import task_id_for
            folder = Path(arguments["project"]).expanduser()
            capsule = CapsulePackager(workspace_path=folder if folder.is_dir() else self.workspace_path).package(
                task_id=task_id_for(folder),
                title=f"{folder.name}: {arguments['goal'][:80]}",
                executive_summary=arguments["summary"],
                goal=arguments["goal"],
                next_action=arguments["next_step"],
                agent_name=arguments.get("app") or "chat-app",
                capture_loose_files=False,
            )
            self.store.save(capsule)
            return json.dumps({"status": "saved", "task_id": capsule.task_id, "capsule_id": capsule.capsule_id})

        elif name == "resume_latest":
            from agent_comms.fleet.autosave import latest, task_id_for
            project = arguments.get("project")
            folder = Path(project).expanduser() if project else self.workspace_path.resolve()
            task_id = arguments.get("task_id") or task_id_for(folder)
            capsule = await asyncio.to_thread(latest, task_id, self.store)
            if not capsule:
                return json.dumps({"error": f"No saved work found for '{task_id}'."})
            res = {"capsule_id": capsule.capsule_id, "briefing": capsule.to_briefing_markdown()}
            if arguments.get("apply_workspace"):
                res["restoration"] = self.unpacker.apply(capsule, apply_workspace=True)["git_patch_message"]
            return json.dumps(res, indent=2)

        elif name == "run_on_agents":
            from agent_comms.fleet import runner
            try:
                folder = arguments.get("folder") or str(self.workspace_path)
                jobs = runner.submit(arguments["tasks"], cwd=str(Path(folder).expanduser()), agent=arguments.get("agent"))
            except Exception as e:
                return json.dumps({"error": str(e)})
            return json.dumps([{"job_id": j["id"], "agent": j["agent"], "task": j["prompt"]} for j in jobs], indent=2)

        elif name == "check_jobs":
            from agent_comms.fleet import runner
            jobs = await asyncio.to_thread(runner.wait, arguments["job_ids"], arguments.get("wait_seconds", 0))
            return json.dumps([
                {k: j.get(k) for k in ("id", "agent", "status", "exit_code", "output")} if j else None
                for j in jobs
            ], indent=2)

        elif name == "agent_status":
            from agent_comms.fleet import runner
            return json.dumps(runner.status(), indent=2)

        return json.dumps({"error": f"Unknown tool: {name}"})

    async def run_stdio(self):
        """Standard IO JSON-RPC 2.0 MCP loop."""
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            # The Proactor loop cannot register the anonymous stdin pipe an MCP
            # client hands us (WinError 6), so connect_read_pipe hangs forever.
            # Read lines on a worker thread instead.
            async def readline():
                return await loop.run_in_executor(None, sys.stdin.buffer.readline)
        else:
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            readline = reader.readline

        while True:
            line = await readline()
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
                        "serverInfo": {"name": "agent-comms-mcp", "version": "1.2.0"},
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
