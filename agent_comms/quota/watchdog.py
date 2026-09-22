"""
Session Watchdog & Preemptive Evacuation Daemon
================================================
Actively monitors running Claude Code and Antigravity sessions in the background.
Detects rate-limit pauses, quota warnings, 429 lockouts, or resource exhaustion
in real-time and immediately checkpoints workspace state into a Context Capsule
before the session terminates or gets blocked.
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent_comms.config import ConfigManager
from agent_comms.quota.guard import QuotaGuard
from agent_comms.quota.models import EvacuationResult

logger = logging.getLogger("agent_comms.quota.watchdog")

# Regex patterns matching vendor rate limits, pauses, and quota warnings
RATE_LIMIT_PATTERNS = [
    re.compile(r"rate-limit-options", re.IGNORECASE),
    re.compile(r"continue automatically at", re.IGNORECASE),
    re.compile(r"exceeded your current quota", re.IGNORECASE),
    re.compile(r"You have reached your usage limit", re.IGNORECASE),
    re.compile(r"rate_limit_error", re.IGNORECASE),
    re.compile(r"Rate limit reached", re.IGNORECASE),
    re.compile(r"RESOURCE_EXHAUSTED", re.IGNORECASE),
    re.compile(r"429 Too Many Requests", re.IGNORECASE),
    re.compile(r"status_code.*429", re.IGNORECASE),
    re.compile(r"\"status\":\s*429", re.IGNORECASE),
    re.compile(r"\"error\":\s*\"rate_limit\"", re.IGNORECASE),
]


class SessionWatchdog:
    """
    Watches active Claude Code and Antigravity transcript/session logs.
    Automatically triggers a Preemptive Quota Evacuation when rate limits are detected.
    """

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        check_interval: float = 3.0,
        max_file_age_seconds: float = 600.0,
    ):
        self.config = config or ConfigManager()
        self.check_interval = check_interval
        self.max_file_age_seconds = max_file_age_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Track already evacuated (session_id, trigger_signature) pairs
        self._evacuated_signatures: Set[str] = set()

    def get_candidate_log_paths(self) -> List[Path]:
        """Discovers potential session log paths across all standard profiles."""
        patterns = []
        is_win = platform.system() == "Windows"

        if is_win:
            userprofile = os.environ.get("USERPROFILE", "")
            if userprofile:
                patterns.extend([
                    os.path.join(userprofile, ".claude", "projects", "*", "*.jsonl"),
                    os.path.join(userprofile, ".gemini", "antigravity-cli", "brain", "*", ".system_generated", "logs", "transcript*.jsonl"),
                ])
        else:
            # Linux and macOS
            home = os.path.expanduser("~")
            patterns.extend([
                os.path.join(home, ".claude", "projects", "*", "*.jsonl"),
                os.path.join(home, ".gemini", "antigravity-cli", "brain", "*", ".system_generated", "logs", "transcript*.jsonl"),
            ])
            # If running as root or with sudo access, also check /root and /home/*
            if os.path.exists("/root/.claude"):
                patterns.append("/root/.claude/projects/*/*.jsonl")
            if os.path.exists("/root/.gemini"):
                patterns.append("/root/.gemini/antigravity-cli/brain/*/.system_generated/logs/transcript*.jsonl")
            for user_dir in glob.glob("/home/*"):
                patterns.append(os.path.join(user_dir, ".claude", "projects", "*", "*.jsonl"))
                patterns.append(os.path.join(user_dir, ".gemini", "antigravity-cli", "brain", "*", ".system_generated", "logs", "transcript*.jsonl"))

        found_files = []
        now = datetime.now().timestamp()
        for pat in patterns:
            for filepath in glob.glob(pat):
                try:
                    p = Path(filepath)
                    if p.is_file():
                        mtime = p.stat().st_mtime
                        if now - mtime <= self.max_file_age_seconds:
                            found_files.append(p)
                except Exception:
                    pass

        return sorted(found_files, key=lambda f: f.stat().st_mtime, reverse=True)

    def scan_session_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parses the tail of a session log file for rate-limit indicators and context.
        """
        try:
            # Read last 64KB for speed
            size = file_path.stat().st_size
            read_size = min(size, 65536)
            with open(file_path, "rb") as f:
                if size > read_size:
                    f.seek(size - read_size)
                raw_bytes = f.read()

            text = raw_bytes.decode("utf-8", errors="ignore")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if not lines:
                return None

            detected_trigger = None
            for line in reversed(lines):
                for pat in RATE_LIMIT_PATTERNS:
                    if pat.search(line):
                        detected_trigger = pat.pattern
                        break
                if detected_trigger:
                    break

            if not detected_trigger:
                return None

            # Extract workspace directory and session ID
            session_id = file_path.stem
            workspace_dir = None
            last_prompt = "Preemptive quota evacuation"
            last_assistant_summary = "Rate limit detected during task execution."

            # Inspect lines in reverse to find metadata
            for line in reversed(lines):
                try:
                    data = json.loads(line)
                    if not workspace_dir:
                        # Claude Code format
                        if "cwd" in data:
                            workspace_dir = data["cwd"]
                        elif "workingDirectory" in data:
                            workspace_dir = data["workingDirectory"]
                        elif "attachment" in data and isinstance(data["attachment"], dict):
                            snap = data["attachment"].get("snapshot", {})
                            if "workingDirectory" in snap:
                                workspace_dir = snap["workingDirectory"]

                    if "sessionId" in data:
                        session_id = data["sessionId"]
                    elif "session_id" in data:
                        session_id = data["session_id"]

                    if "lastPrompt" in data and data["lastPrompt"]:
                        last_prompt = str(data["lastPrompt"])

                    if "message" in data and isinstance(data["message"], dict):
                        content = data["message"].get("content")
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    last_assistant_summary = item.get("text", "")[:500]
                                    break
                except Exception:
                    continue

            # Fallback for workspace directory
            if not workspace_dir or not Path(workspace_dir).exists():
                # Try inferring from file path or parent project folder
                # e.g., ~/.claude/projects/-home-ubuntu-myproject -> /home/ubuntu/myproject
                parent_proj = file_path.parent.name
                if parent_proj.startswith("-"):
                    candidate = "/" + parent_proj[1:].replace("-", "/")
                    if Path(candidate).exists():
                        workspace_dir = candidate
                elif Path.cwd().exists():
                    workspace_dir = str(Path.cwd())

            return {
                "file_path": str(file_path),
                "session_id": session_id,
                "workspace_dir": workspace_dir or str(Path.cwd()),
                "trigger": detected_trigger,
                "last_prompt": last_prompt,
                "summary": last_assistant_summary,
                "mtime": file_path.stat().st_mtime,
            }

        except Exception as e:
            logger.debug("Error scanning session file %s: %s", file_path, e)
            return None

    def evacuate(self, session_info: Dict[str, Any]) -> Optional[EvacuationResult]:
        """
        Executes an autonomous Preemptive Evacuation for a detected rate-limit event.
        """
        session_id = session_info["session_id"]
        trigger = session_info["trigger"]
        mtime = session_info.get("mtime", 0)

        # Signature deduplication: do not evacuate the same turn twice
        sig = f"{session_id}:{trigger}:{int(mtime // 60)}"
        if sig in self._evacuated_signatures:
            return None

        workspace_path = Path(session_info["workspace_dir"]).resolve()
        if not workspace_path.exists():
            workspace_path = Path.cwd().resolve()

        provider = "anthropic" if "claude" in session_info.get("file_path", "").lower() else "gemini"

        logger.warning(
            "[!] SessionWatchdog: Rate limit trigger '%s' detected in session '%s' at %s. Evacuating...",
            trigger,
            session_id,
            workspace_path,
        )
        print(f"\n==================================================================")
        print(f" [!] PREEMPTIVE QUOTA GUARD: Rate Limit Detected!")
        print(f" [+] Trigger: '{trigger}' in session '{session_id}'")
        print(f" [+] Workspace: {workspace_path}")
        print(f" [+] Freezing workspace changes into Context Capsule...")

        guard = QuotaGuard(workspace_path=workspace_path)
        auto_cloud = bool(self.config.get("default_cloud_provider"))

        result = guard.force_evacuate(
            task_id=session_id,
            provider=provider,
            summary=f"Autonomous Preemptive Evacuation: Triggered by '{trigger}' in {session_id}",
            title=f"Task {session_id} (Rate Limit Evacuation)",
            next_action=f"Resume task '{session_info['last_prompt']}' using successor provider or peer node",
            auto_push_cloud=auto_cloud,
            cloud_provider=self.config.get("default_cloud_provider", "relay"),
        )

        self._evacuated_signatures.add(sig)

        # Write immediate briefing file directly to workspace root for instant visibility
        try:
            briefing_file = workspace_path / "PREEMPTIVE_EVACUATION_BRIEFING.md"
            briefing_content = (
                f"# Preemptive Quota Evacuation Notice\n\n"
                f"**Task ID:** `{session_id}`  \n"
                f"**Capsule ID:** `{result.capsule_id}`  \n"
                f"**Timestamp:** `{datetime.now(timezone.utc).isoformat()}`  \n"
                f"**Trigger Reason:** Rate limit pattern `{trigger}` detected.  \n"
                f"**Saved Capsule:** `{result.saved_path}`  \n"
                f"{f'**Cloud Location:** `{result.cloud_location}`' if result.cloud_location else ''}\n\n"
                f"## Resumption Prompt for Successor Model / Machine:\n\n"
                f"```text\n{result.resumption_prompt}\n```\n\n"
                f"---\n\n"
                f"{result.briefing}\n"
            )
            briefing_file.write_text(briefing_content, encoding="utf-8")
            print(f" [+] Wrote workspace briefing to: {briefing_file}")
        except Exception as ex:
            logger.debug("Could not write briefing file: %s", ex)

        print(f" [+] Evacuation Capsule created: {result.capsule_id}")
        if result.cloud_location:
            print(f" [+] Uploaded to cloud: {result.cloud_location}")
        print(f"==================================================================\n")

        return result

    def check_once(self) -> List[EvacuationResult]:
        """Performs a single scan of active sessions and evacuates if needed."""
        evacuations = []
        files = self.get_candidate_log_paths()
        for f in files:
            info = self.scan_session_file(f)
            if info:
                res = self.evacuate(info)
                if res:
                    evacuations.append(res)
        return evacuations

    async def run_loop(self):
        """Continuously monitors active sessions."""
        self._running = True
        logger.info("SessionWatchdog started with check interval %.1fs", self.check_interval)
        while self._running:
            try:
                await asyncio.to_thread(self.check_once)
            except Exception as e:
                logger.debug("Error in SessionWatchdog loop: %s", e)
            await asyncio.sleep(self.check_interval)

    def start(self):
        """Starts watchdog background task."""
        if not self._task or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self.run_loop())

    def stop(self):
        """Stops watchdog background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
