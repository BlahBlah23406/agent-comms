"""
GitHub Gist Cloud Provider
==========================
Uses GitHub's Gist REST API to store and retrieve Context Capsules.
Zero extra dependencies required (uses standard library urllib).
Allows developers with GITHUB_TOKEN or 'gh' CLI to share capsules effortlessly.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider, CloudCapsuleRecord
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.cloud.github")


class GitHubCloudProvider(BaseCloudProvider):
    name = "github"

    def __init__(self, token: Optional[str] = None):
        self.token = token or self._resolve_token()

    def _resolve_token(self) -> str:
        # 1. ConfigManager or GITHUB_TOKEN / GH_TOKEN env
        tok = config_manager.get("github.token", "")
        if tok:
            return tok
        env_tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if env_tok:
            return env_tok
        # 2. Try 'gh auth token' if GitHub CLI is installed
        try:
            res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    def _check_token(self):
        if not self.token:
            raise ValueError(
                "GitHub token not found. Set via: agent-comms config set github.token <token>, "
                "GITHUB_TOKEN environment variable, or login via 'gh auth login'."
            )

    def _request(self, method: str, url: str, data: Optional[Dict[str, Any]] = None) -> Any:
        self._check_token()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-comms-capsule-sync/1.0",
        }
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error ({e.code}): {err_msg}")

    def upload(self, capsule: ContextCapsule) -> str:
        filename_json = f"{capsule.task_id}_{capsule.capsule_id}.json"
        filename_md = f"{capsule.task_id}_{capsule.capsule_id}.md"

        payload = {
            "description": f"[agent-comms] Context Capsule for {capsule.task_id}: {capsule.title}",
            "public": False,  # Secret Gist by default for safety
            "files": {
                filename_json: {
                    "content": capsule.model_dump_json(indent=2)
                },
                filename_md: {
                    "content": capsule.to_briefing_markdown()
                }
            }
        }

        resp = self._request("POST", "https://api.github.com/gists", payload)
        gist_id = resp.get("id")
        html_url = resp.get("html_url")
        logger.info("Created GitHub Gist capsule: %s (%s)", gist_id, html_url)
        return f"github://gist/{gist_id}"

    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        gist_id = None
        if capsule_id_or_uri.startswith("github://gist/"):
            gist_id = capsule_id_or_uri.replace("github://gist/", "").strip()
        elif "gist.github.com" in capsule_id_or_uri:
            gist_id = capsule_id_or_uri.rstrip("/").split("/")[-1]
        elif len(capsule_id_or_uri) == 32 and not capsule_id_or_uri.startswith("capsule-"):
            # Hex Gist ID
            gist_id = capsule_id_or_uri
        else:
            # Search user's gists for matching capsule ID
            gists = self.list_capsules()
            for g in gists:
                if capsule_id_or_uri in g.capsule_id or capsule_id_or_uri in g.task_id:
                    gist_id = g.location.replace("github://gist/", "")
                    break

        if not gist_id:
            raise FileNotFoundError(f"Could not find GitHub Gist matching '{capsule_id_or_uri}'")

        resp = self._request("GET", f"https://api.github.com/gists/{gist_id}")
        files = resp.get("files", {})

        # Find the JSON file
        for fname, fmeta in files.items():
            if fname.endswith(".json"):
                content = fmeta.get("content")
                if not content and fmeta.get("raw_url"):
                    with urllib.request.urlopen(fmeta["raw_url"]) as raw_resp:
                        content = raw_resp.read().decode("utf-8")
                if content:
                    return ContextCapsule.model_validate(json.loads(content))

        raise FileNotFoundError(f"No JSON capsule file found in Gist '{gist_id}'")

    def list_capsules(self) -> List[CloudCapsuleRecord]:
        resp = self._request("GET", "https://api.github.com/gists?per_page=100")
        records: List[CloudCapsuleRecord] = []

        for gist in resp:
            desc = gist.get("description", "")
            if "[agent-comms]" not in desc:
                continue

            files = gist.get("files", {})
            for fname, fmeta in files.items():
                if fname.endswith(".json"):
                    parts = fname[:-5].split("_", 1)
                    task_id = parts[0] if len(parts) > 0 else "unknown"
                    capsule_id = parts[1] if len(parts) > 1 else fname[:-5]

                    clean_summary = desc.replace("[agent-comms]", "").strip()
                    records.append(
                        CloudCapsuleRecord(
                            capsule_id=capsule_id,
                            task_id=task_id,
                            created_at=gist.get("created_at", ""),
                            summary=clean_summary,
                            provider="github",
                            location=f"github://gist/{gist.get('id')}",
                            size_bytes=fmeta.get("size"),
                        )
                    )

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def delete(self, capsule_id_or_uri: str) -> bool:
        gist_id = capsule_id_or_uri.replace("github://gist/", "").strip()
        try:
            self._request("DELETE", f"https://api.github.com/gists/{gist_id}")
            return True
        except Exception:
            return False
