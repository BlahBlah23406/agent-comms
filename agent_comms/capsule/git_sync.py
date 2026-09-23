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
            if res.returncode != 0 or res.stdout.strip() != "true":
                return False
            # Check if this workspace path is ignored by an enclosing git repository
            res_ignore = self._run_git(["check-ignore", "-q", "."], check=False)
            if res_ignore.returncode == 0:
                return False
            return True
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
        Captures the unified diff of both staged and unstaged tracked modifications
        scoped to this workspace path.
        """
        if not self.is_git_repo():
            return ""
        # HEAD diff includes both staged and unstaged tracked changes in workspace
        res = self._run_git(["diff", "HEAD", "--", "."], check=False)
        if res.returncode == 0:
            return res.stdout
        # Fallback if no commits exist yet
        res = self._run_git(["diff", "--", "."], check=False)
        return res.stdout if res.returncode == 0 else ""

    def get_modified_files(self) -> List[str]:
        if not self.is_git_repo():
            return []
        repo_root = self.get_repo_root() or self.workspace_path
        res = self._run_git(["status", "--porcelain", "."], check=False)
        if res.returncode != 0:
            return []
        modified = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            status = line[:2]
            raw_path = line[3:].strip().replace("\\", "/")
            if status != "??":
                full_path = (repo_root / raw_path).resolve()
                try:
                    clean_rel = str(full_path.relative_to(self.workspace_path)).replace("\\", "/")
                except ValueError:
                    clean_rel = raw_path
                modified.append(clean_rel)
        return modified

    def get_untracked_files(self, max_file_size_kb: int = 1024) -> Dict[str, str]:
        """
        Detects untracked files and reads their contents.
        Encodes binary files with 'base64:' prefix.
        If not a git repo, collects workspace files directly.
        """
        untracked: Dict[str, str] = {}
        ignored_dirs = {
            "node_modules", ".next", ".venv", "venv", "__pycache__", ".git", ".tmp",
            "dist", "build", "coverage", ".cache", "tmp", "temp"
        }
        max_untracked_count = 100
        files_to_read = []

        if not self.is_git_repo():
            for root, dirs, files in os.walk(self.workspace_path):
                dirs[:] = [d for d in dirs if d not in ignored_dirs]
                for f in files:
                    if len(files_to_read) >= max_untracked_count:
                        break
                    if f in ignored_dirs:
                        continue
                    f_path = Path(root) / f
                    sub_rel = str(f_path.relative_to(self.workspace_path)).replace("\\", "/")
                    files_to_read.append((sub_rel, f_path))
                if len(files_to_read) >= max_untracked_count:
                    break
        else:
            repo_root = self.get_repo_root() or self.workspace_path
            res = self._run_git(["status", "--porcelain", "-uall", "."], check=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if len(files_to_read) >= max_untracked_count:
                        break
                    line = line.strip()
                    if line.startswith("?? "):
                        raw_rel = line[3:].strip().replace("\\", "/")
                        parts = raw_rel.split("/")
                        if any(p in ignored_dirs for p in parts):
                            continue

                        full_path = (repo_root / raw_rel).resolve()
                        try:
                            clean_rel = str(full_path.relative_to(self.workspace_path)).replace("\\", "/")
                        except ValueError:
                            clean_rel = raw_rel

                        if full_path.is_file():
                            files_to_read.append((clean_rel, full_path))
                        elif full_path.is_dir():
                            for root, dirs, files in os.walk(full_path):
                                root_parts = Path(root).relative_to(self.workspace_path).parts
                                if any(p in ignored_dirs for p in root_parts):
                                    dirs[:] = []
                                    continue
                                dirs[:] = [d for d in dirs if d not in ignored_dirs]
                                for f in files:
                                    if len(files_to_read) >= max_untracked_count:
                                        break
                                    if f in ignored_dirs:
                                        continue
                                    f_path = Path(root) / f
                                    sub_rel = str(f_path.relative_to(self.workspace_path)).replace("\\", "/")
                                    files_to_read.append((sub_rel, f_path))
                                if len(files_to_read) >= max_untracked_count:
                                    break

        for f_rel, f_full in files_to_read:
            if len(untracked) >= max_untracked_count:
                break
            try:
                size_kb = f_full.stat().st_size / 1024
                if size_kb > max_file_size_kb:
                    continue
                content = f_full.read_text(encoding="utf-8")
                untracked[f_rel] = content
            except UnicodeDecodeError:
                try:
                    raw = f_full.read_bytes()
                    untracked[f_rel] = "base64:" + base64.b64encode(raw).decode("ascii")
                except Exception:
                    continue
            except Exception:
                continue
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
