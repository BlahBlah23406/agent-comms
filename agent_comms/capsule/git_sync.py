"""
Git Synchronization and Patch Utilities
=======================================
Provides Git introspection, diff capture, untracked file handling,
and patch application for seamless workspace state transfer.
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class GitHelper:
    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path.resolve()

    def _run_git(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
        )

    def is_git_repo(self) -> bool:
        try:
            res = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
            return res.returncode == 0 and res.stdout.strip() == "true"
        except FileNotFoundError:
            return False

    def get_repo_root(self) -> Optional[Path]:
        if not self.is_git_repo():
            return None
        res = self._run_git(["rev-parse", "--show-toplevel"], check=False)
        if res.returncode == 0:
            return Path(res.stdout.strip())
        return None

    def get_current_branch(self) -> str:
        if not self.is_git_repo():
            return "none"
        res = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        return res.stdout.strip() if res.returncode == 0 else "detached"

    def get_head_commit(self) -> str:
        if not self.is_git_repo():
            return "none"
        res = self._run_git(["rev-parse", "HEAD"], check=False)
        return res.stdout.strip() if res.returncode == 0 else "unknown"

    def get_git_diff(self) -> str:
        """
        Captures the unified diff of both staged and unstaged tracked modifications.
        """
        if not self.is_git_repo():
            return ""
        # HEAD diff includes both staged and unstaged tracked changes
        res = self._run_git(["diff", "HEAD"], check=False)
        if res.returncode == 0:
            return res.stdout
        # Fallback if no commits exist yet
        res = self._run_git(["diff"], check=False)
        return res.stdout if res.returncode == 0 else ""

    def get_modified_files(self) -> List[str]:
        if not self.is_git_repo():
            return []
        res = self._run_git(["status", "--porcelain"], check=False)
        if res.returncode != 0:
            return []
        modified = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            status = line[:2]
            filepath = line[3:].strip()
            if status != "??":
                modified.append(filepath)
        return modified

    def get_untracked_files(self, max_file_size_kb: int = 1024) -> Dict[str, str]:
        """
        Detects untracked files and reads their contents.
        Encodes binary files with 'base64:' prefix.
        """
        if not self.is_git_repo():
            return {}
        # -uall forces git to list individual untracked files instead of collapsing directories
        res = self._run_git(["status", "--porcelain", "-uall"], check=False)
        if res.returncode != 0:
            return {}

        untracked: Dict[str, str] = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("?? "):
                rel_path = line[3:].strip()
                full_path = self.workspace_path / rel_path
                files_to_read = []
                if full_path.is_file():
                    files_to_read.append((rel_path, full_path))
                elif full_path.is_dir():
                    for sub_file in full_path.rglob("*"):
                        if sub_file.is_file():
                            sub_rel = str(sub_file.relative_to(self.workspace_path)).replace("\\", "/")
                            files_to_read.append((sub_rel, sub_file))

                for f_rel, f_full in files_to_read:
                    size_kb = f_full.stat().st_size / 1024
                    if size_kb > max_file_size_kb:
                        continue
                    try:
                        content = f_full.read_text(encoding="utf-8")
                        untracked[f_rel] = content
                    except UnicodeDecodeError:
                        raw = f_full.read_bytes()
                        untracked[f_rel] = "base64:" + base64.b64encode(raw).decode("ascii")
        return untracked

    def apply_patch(self, diff_content: str) -> Tuple[bool, str]:
        """
        Applies a unified git diff cleanly with whitespace tolerance.
        Tries direct application first, falls back to 3-way merge if needed.
        """
        if not self.is_git_repo() or not diff_content.strip():
            return True, "No git diff to apply."

        # 1. Primary: Direct application with whitespace tolerance
        args = ["apply", "--whitespace=nowarn", "--ignore-space-change", "--ignore-whitespace", "-"]
        p = subprocess.Popen(
            ["git"] + args,
            cwd=str(self.workspace_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        stdout, stderr = p.communicate(input=diff_content)
        if p.returncode == 0:
            return True, "Git patch applied successfully."

        # 2. Fallback: 3-way merge
        p_3way = subprocess.Popen(
            ["git", "apply", "-3", "--whitespace=nowarn", "-"],
            cwd=str(self.workspace_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        stdout_3way, stderr_3way = p_3way.communicate(input=diff_content)
        if p_3way.returncode == 0:
            return True, "Git patch applied via 3-way merge."

        return False, f"Git apply failed: {stderr.strip()}"

    def write_untracked_files(self, untracked: Dict[str, str], overwrite: bool = True) -> List[str]:
        """
        Writes serialized untracked files to disk.
        """
        written = []
        for rel_path, content in untracked.items():
            dest = self.workspace_path / rel_path
            if dest.exists() and not overwrite:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if content.startswith("base64:"):
                raw = base64.b64decode(content[7:])
                dest.write_bytes(raw)
            else:
                dest.write_text(content, encoding="utf-8")
            written.append(rel_path)
        return written
