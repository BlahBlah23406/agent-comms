"""
Context Capsule Data Models
===========================
Defines the schema for serializing, persisting, and transferring an agent's
mental model, task graph, epistemic learnings, and workspace state across
sessions, machines, and diverse agent implementations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class LearningCategory(str, Enum):
    FINDING = "finding"                  # Discovered fact or verified behavior
    REJECTED_HYPOTHESIS = "rejected"     # What was attempted and failed, preventing loops
    GOTCHA = "gotcha"                    # Non-obvious edge cases, quirks, pitfalls
    ENVIRONMENT = "environment"          # Special tool versions, environment configs, paths
    USER_CONSTRAINT = "constraint"       # Explicit user preferences or invariants


class AgentMetadata(BaseModel):
    agent_name: str = Field(..., description="Name of the agent, e.g. Antigravity, Claude, AutoGen")
    agent_version: str = Field("1.0.0", description="Agent software/framework version")
    machine_id: str = Field(..., description="Hostname or machine identifier")
    os_name: str = Field(..., description="Operating system e.g. Windows, Linux, Darwin")
    session_id: Optional[str] = Field(None, description="Source conversation or session ID")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EpistemicLearning(BaseModel):
    category: LearningCategory = Field(..., description="Type of learning")
    summary: str = Field(..., description="One-line summary of the learning")
    details: Optional[str] = Field(None, description="In-depth explanation, logs, or error text")
    evidence: Optional[str] = Field(None, description="Command or code snippet verifying this")


class TaskStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = Field(..., description="Description of the step")
    status: StepStatus = Field(default=StepStatus.PENDING)
    notes: Optional[str] = Field(None, description="Notes on execution or output")


class TaskGraph(BaseModel):
    goal: str = Field(..., description="High-level goal of the overall task")
    steps: List[TaskStep] = Field(default_factory=list)
    next_action: Optional[str] = Field(None, description="Immediate next step for the successor agent")


class WorkspacePatch(BaseModel):
    is_git_repo: bool = Field(False)
    repo_root: Optional[str] = Field(None)
    branch_name: Optional[str] = Field(None)
    base_commit: Optional[str] = Field(None)
    git_diff: Optional[str] = Field(None, description="Unified git diff of staged + unstaged changes")
    untracked_files: Dict[str, str] = Field(default_factory=dict, description="Relative path -> file content")
    modified_files: List[str] = Field(default_factory=list, description="List of modified file paths")
    git_status_raw: Optional[str] = Field(None)


class ContextCapsule(BaseModel):
    schema_version: str = Field("1.0.0", description="Capsule schema specification version")
    capsule_id: str = Field(default_factory=lambda: f"capsule-{uuid.uuid4().hex[:12]}")
    task_id: str = Field(..., description="Identifier for the task or issue")
    title: str = Field(..., description="Descriptive title of the work unit")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    generator: AgentMetadata = Field(..., description="Metadata of the originating agent & machine")
    target_agent: Optional[str] = Field(None, description="Optional intended recipient or None for broadcast")
    executive_summary: str = Field(..., description="Concise summary of work completed and current status")
    task_graph: TaskGraph = Field(..., description="Task progress and remaining roadmap")
    epistemic_learnings: List[EpistemicLearning] = Field(default_factory=list)
    workspace: WorkspacePatch = Field(default_factory=WorkspacePatch)
    resumption_prompt: Optional[str] = Field(None, description="Direct ready-to-use prompt for next agent")
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_briefing_markdown(self) -> str:
        """
        Renders a structured, token-efficient Markdown briefing specifically designed
        to be prepended into an incoming agent's system prompt or initial turn.
        """
        lines = [
            f"# Context Capsule Handover: {self.title}",
            f"- **Task ID:** `{self.task_id}`",
            f"- **Capsule ID:** `{self.capsule_id}`",
            f"- **Origin:** Agent `{self.generator.agent_name}` on `{self.generator.machine_id}` ({self.generator.os_name})",
            f"- **Timestamp:** {self.created_at}",
            "",
            "## Executive Summary",
            self.executive_summary,
            "",
            "## Task Roadmap",
            f"**Goal:** {self.task_graph.goal}",
            "",
        ]

        if self.task_graph.steps:
            for s in self.task_graph.steps:
                icon = {
                    StepStatus.COMPLETED: "[x]",
                    StepStatus.IN_PROGRESS: "[>]",
                    StepStatus.BLOCKED: "[!]",
                    StepStatus.SKIPPED: "[-]",
                    StepStatus.PENDING: "[ ]",
                }.get(s.status, "[ ]")
                notes_str = f" - *{s.notes}*" if s.notes else ""
                lines.append(f"- {icon} **{s.description}**{notes_str}")

        if self.task_graph.next_action:
            lines.extend([
                "",
                "### Immediate Next Recommended Action",
                f"> {self.task_graph.next_action}",
            ])

        if self.epistemic_learnings:
            lines.extend(["", "## Epistemic Learnings & Discovered Constraints"])
            for learn in self.epistemic_learnings:
                badge = f"[{learn.category.value.upper()}]"
                lines.append(f"- **{badge} {learn.summary}**")
                if learn.details:
                    lines.append(f"  - *Details:* {learn.details}")
                if learn.evidence:
                    lines.append(f"  - *Verification:* `{learn.evidence}`")

        lines.extend([
            "",
            "## Workspace State",
            f"- **Git Repository:** {'Yes' if self.workspace.is_git_repo else 'No'}",
        ])
        if self.workspace.is_git_repo:
            lines.append(f"- **Branch:** `{self.workspace.branch_name}` | **Base Commit:** `{self.workspace.base_commit}`")
        if self.workspace.modified_files:
            lines.append(f"- **Modified Files:** {', '.join(f'`{f}`' for f in self.workspace.modified_files)}")
        if self.workspace.untracked_files:
            lines.append(f"- **New Untracked Files:** {', '.join(f'`{f}`' for f in self.workspace.untracked_files.keys())}")

        if self.resumption_prompt:
            lines.extend([
                "",
                "## Resumption Instructions for Successor Agent",
                self.resumption_prompt,
            ])

        return "\n".join(lines)
