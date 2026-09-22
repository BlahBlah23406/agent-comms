"""
Agent Comms Configuration Manager
=================================
Manages local configuration, cloud provider credentials, and machine identity.
Persists settings to ~/.agent-comms/config.json with environment variable overrides.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """Manages reading and writing persistent agent-comms configuration."""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "machine_alias": socket.gethostname(),
        "default_cloud_provider": "relay",
        "discovery_port": 8764,
        "default_relay_url": "ws://localhost:8765/ws",
        "s3": {
            "bucket": "",
            "region": "us-east-1",
            "endpoint_url": "",
            "access_key_id": "",
            "secret_access_key": "",
        },
        "gcs": {
            "bucket": "",
            "project": "",
            "credentials_file": "",
        },
        "azure": {
            "connection_string": "",
            "container_name": "capsules",
        },
        "github": {
            "token": "",
            "gist_id": "",
        },
    }

    def __init__(self, config_path: Optional[Path] = None):
        self.config_dir = (config_path or (Path.home() / ".agent-comms")).resolve()
        self.config_file = self.config_dir / "config.json"
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from file or initializes with defaults."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if self.config_file.exists():
            try:
                content = self.config_file.read_text(encoding="utf-8")
                loaded = json.loads(content)
                self._data = self._merge_dicts(self.DEFAULT_CONFIG, loaded)
            except Exception:
                self._data = dict(self.DEFAULT_CONFIG)
        else:
            self._data = dict(self.DEFAULT_CONFIG)
            self.save()
        return self._data

    def save(self):
        """Persists current configuration to disk."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def _merge_dicts(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._merge_dicts(result[k], v)
            else:
                result[k] = v
        return result

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Retrieves a config value by dot-notated key path (e.g. 's3.bucket').
        Checks environment variables first as overrides.
        """
        env_val = self._get_from_env(key_path)
        if env_val is not None:
            return env_val

        parts = key_path.split(".")
        curr = self._data
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return default
        return curr if curr != "" else default

    def set(self, key_path: str, value: Any):
        """Sets a configuration value by dot-notated key path and persists to disk."""
        parts = key_path.split(".")
        curr = self._data
        for p in parts[:-1]:
            if p not in curr or not isinstance(curr[p], dict):
                curr[p] = {}
            curr = curr[p]
        curr[parts[-1]] = value
        self.save()

    def get_all(self) -> Dict[str, Any]:
        """Returns full configuration dict."""
        return self._data

    def _get_from_env(self, key_path: str) -> Optional[str]:
        """Maps dot-notated keys to common environment variable names."""
        env_map = {
            "default_cloud_provider": "AGENT_COMMS_CLOUD_PROVIDER",
            "machine_alias": "AGENT_COMMS_MACHINE_ALIAS",
            "discovery_port": "AGENT_COMMS_DISCOVERY_PORT",
            "default_relay_url": "AGENT_COMMS_RELAY_URL",
            "s3.bucket": "AWS_S3_BUCKET",
            "s3.region": "AWS_REGION",
            "s3.endpoint_url": "AWS_ENDPOINT_URL",
            "s3.access_key_id": "AWS_ACCESS_KEY_ID",
            "s3.secret_access_key": "AWS_SECRET_ACCESS_KEY",
            "gcs.bucket": "GCS_BUCKET",
            "gcs.project": "GOOGLE_CLOUD_PROJECT",
            "gcs.credentials_file": "GOOGLE_APPLICATION_CREDENTIALS",
            "azure.connection_string": "AZURE_STORAGE_CONNECTION_STRING",
            "azure.container_name": "AZURE_STORAGE_CONTAINER",
            "github.token": "GITHUB_TOKEN",
            "github.gist_id": "GITHUB_GIST_ID",
        }
        env_var = env_map.get(key_path)
        if env_var and os.environ.get(env_var):
            return os.environ[env_var]
        return None

    def resolve_cloud_provider(self, requested: Optional[str] = None) -> str:
        """
        Determines active cloud provider based on:
        1. Explicit request
        2. Config / Environment default
        3. Automatic detection from environment variables
        """
        if requested:
            return requested.lower().strip()

        configured = self.get("default_cloud_provider")
        if configured and configured != "relay":
            return configured

        # Auto-detection
        if os.environ.get("AWS_S3_BUCKET") or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")):
            return "s3"
        if os.environ.get("GCS_BUCKET") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            return "gcs"
        if os.environ.get("AZURE_STORAGE_CONNECTION_STRING"):
            return "azure"
        if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
            return "github"

        return configured or "relay"


# Global singleton instance
config_manager = ConfigManager()
