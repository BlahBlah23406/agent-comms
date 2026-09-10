"""
Model Context Protocol (MCP) Server
===================================
Exposes Context Capsule handoff and Live Relay features as standardized
MCP tools for AI assistants (Antigravity, Claude, Cursor, Windsurf, etc.).
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


class AgentCommsMCPServer:
    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace_path = workspace_path or Path.cwd()
        self.store = CapsuleStore()
        self.packager = CapsulePackager(workspace_path=self.workspace_path, store=self.store)
        self.unpacker = CapsuleUnpacker(workspace_path=self.workspace_path)

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "export_handoff_capsule",
                "description": "Packages current task progress, epistemic learnings, git changes, and next steps into a transferable Context Capsule.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Unique task or issue ID"},
                        "title": {"type": "string", "description": "Descriptive title"},
                        "goal": {"type": "string", "description": "Overall task goal"},
                        "executive_summary": {"type": "string", "description": "Summary of work done so far"},
                        "next_action": {"type": "string", "description": "Specific next instruction for successor agent"},
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
                "description": "Imports and applies a Context Capsule from another agent/machine, restoring workspace changes and briefing context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capsule_or_task_id": {"type": "string", "description": "ID of the capsule or task to import"},
                        "apply_workspace": {"type": "boolean", "default": True, "description": "Whether to apply git diffs and untracked files"},
                    },
                    "required": ["capsule_or_task_id"],
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
        ]

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> str:
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
            return json.dumps({
                "status": "success",
                "capsule_id": capsule.capsule_id,
                "saved_path": str(saved_path),
                "briefing": capsule.to_briefing_markdown(),
            }, indent=2)

        elif name == "import_handoff_capsule":
            target_id = arguments["capsule_or_task_id"]
            capsule = self.store.load_by_id(target_id)
            if not capsule:
                # Check if it's a direct path
                p = Path(target_id)
                if p.exists() and p.is_file():
                    capsule = self.store.load_from_file(p)
            if not capsule:
                return json.dumps({"error": f"Capsule '{target_id}' not found."}, indent=2)

            apply_ws = arguments.get("apply_workspace", True)
            res = self.unpacker.apply(capsule, apply_workspace=apply_ws)
            return json.dumps({
                "status": "success",
                "restoration": res,
                "resumption_prompt": capsule.resumption_prompt,
            }, indent=2)

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
                        "serverInfo": {"name": "agent-comms-mcp", "version": "1.0.0"},
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
                tool_result = self.handle_tool_call(tool_name, args)
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
