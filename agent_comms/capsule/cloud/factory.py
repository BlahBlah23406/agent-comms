"""
Cloud Storage Provider Factory
==============================
Resolves and instantiates the appropriate cloud/unified storage provider.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider
from agent_comms.capsule.cloud.s3 import S3CloudProvider
from agent_comms.capsule.cloud.gcs import GCSCloudProvider
from agent_comms.capsule.cloud.azure import AzureBlobCloudProvider
from agent_comms.capsule.cloud.github import GitHubCloudProvider
from agent_comms.capsule.cloud.relay import RelayCloudProvider, StorageServerProvider
from agent_comms.config import config_manager


def get_cloud_provider(
    provider_name: Optional[str] = None,
    **kwargs: Any,
) -> BaseCloudProvider:
    """
    Factory resolving provider instance by name, configuration, or environment.
    Supported: 'storage', 'server', 'relay', 's3', 'gcs', 'azure', 'github'
    """
    name = config_manager.resolve_cloud_provider(provider_name)

    if name in ("storage", "server", "unified"):
        return StorageServerProvider(**kwargs)
    elif name == "relay":
        return RelayCloudProvider(**kwargs)
    elif name == "s3":
        return S3CloudProvider(**kwargs)
    elif name == "gcs":
        return GCSCloudProvider(**kwargs)
    elif name == "azure":
        return AzureBlobCloudProvider(**kwargs)
    elif name in ("github", "gist"):
        return GitHubCloudProvider(**kwargs)
    else:
        # Default fallback to unified storage / relay provider
        return StorageServerProvider(**kwargs)
